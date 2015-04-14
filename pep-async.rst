PEP: XXX
Title: Coroutines with async and await syntax
Version: $Revision$
Last-Modified: $Date$
Author: Yury Selivanov <yselivanov@sprymix.com>
Discussions-To: Python-Dev <python-dev@python.org>
Python-Version: 3.5
Status: Draft
Type: Standards Track
Content-Type: text/x-rst
Created: 09-Apr-2015
Post-History:
Resolution:


Abstract
========

This PEP introduces a new syntax for coroutines, asynchronous ``with``
statements and ``for`` loops.  The main motivation behind this proposal is to
streamline writing and maintaining asynchronous code, as well as to simplify
previously hard to implement code patterns.


Rationale and Goals
===================

Coroutines in Python are usually implemented using generators and the ``yield
from`` syntax.  Documentation of the [asyncio]_ module in the standard library
recommends using the ``\@asyncio.coroutine`` decorator to state intent
(documentation) and ease debugging (developer efficiency).  This approach
requires users to understand generators, most importantly the difference between
``yield`` and ``yield from``. Existing Python 2-compatible third-party
frameworks, including the ``asyncio`` backport [trollius]_, implement coroutines
using ``yield`` and trampolines, adding to the confusion.

This proposal makes coroutines a first class construct in Python to clearly
separate them from generators.  This allows unambiguous usage of generators and
coroutines close to each other, as well as helps to avoid intermixing them by
mistake.  It also enables linters and IDEs to improve code static analysis and
refactoring.

Introducing the ``async`` keyword enables creation of asynchronous context
manager and iteration protocols.  The former lets Python perform non-blocking
operations upon entering and exiting the context manager, while the latter lets
Python perform non-blocking operations during iteration steps (in an equivalent
of ``__next__()``).


Specification
=============

async/await aren't new concepts in computer languages. C# has had it for years,
and there are proposals to add them in C++ and JavaScript.


New Coroutines Declaration Syntax
---------------------------------

Use ``async`` and ``def`` keywords to declare a coroutine::

    async def read_data(db):
        ...

Coroutines are always generators, even if they do not contain ``await``
expressions.

It's a syntax error to have ``yield`` or ``yield from`` expressions in ``async``
function.

A new bit flag ``CO_ASYNC`` for ``co_flag`` field of code objects will be
introduced to allow runtime detection of coroutine objects.

To make sure that asynchronous functions are always awaited on, the generator
object's ``tp_finalize`` implementation will be tweaked to raise a
``RuntimeWarning`` if the ``send`` method was never called on it (only for
functions with ``CO_ASYNC`` bit in ``co_flag``).  This is an extremely important
feature, since omitting a ``yield from`` is a common mistake.
``\@asyncio.coroutine`` decorator addresses the problem by wrapping generators
with a special object in asyncio debug mode; however, we believe, that only
a small fraction of asyncio users knows about it::

    async def read():
        ...
    # later in the code:
    read() # this line will raise a warning

``StopIteration`` exceptions will not be propagated out of async functions. This
feature can be enabled for regular generators in CPython 3.5 with a special
future import statement (see PEP 479).  Since the new syntax will not require
future imports nor it was possible to have async functions before 3.5, it is
safe to enable this feature by default.


Await Expression
----------------

Await expression is almost a direct equivalent of ``yield from``::

    async def read_data(db):
        data = await db.fetch('SELECT ...')
        ...

It will share most of the ``yield from`` implementation with an extra step of
validating its argument.  It will only accept:

 * ``async`` functions;

 * generators with ``CO_ASYNC`` in their ``gi_code.co_flags``;

 * objects with its ``__iter__`` method tagged with ``__async__ = True``
   attribute.  This is to enable backwards compatibility and to enable use of
   bare ``yield`` statements to suspend code execution in a chain of ``await``
   calls.  We will call such objects as *Future-like* objects in the rest of
   this PEP.

It is a ``SyntaxError`` to use ``await`` outside of an ``async`` function.

A new function is added to ``types`` module: ``asyncdef(gen)``.  It adds
``CO_ASYNC`` bit to the passed generator's code object, so that it can be
awaited on in async functions.  This is how all asyncio code and its libraries
will automatically benefit from this proposal.


Asynchronous Context Managers and "async with"
----------------------------------------------

An asynchronous Context Manager will be able to suspend execution in its *enter*
and *exit* methods.

To make it possible we propose to add a new protocol for asynchronous context
managers. Two new magic methods will be added: ``__aenter__`` and
``__aexit__``.  Both must either return a *Future-like* object, or be an
``async`` function.

We propose a new statement for the new protocol::

    async with EXPR as VAR:
        BLOCK


which is roughly equivalent to::

    mgr = (EXPR)
    aexit = type(mgr).__aexit__
    aenter = type(mgr).__aenter__(mgr)
    exc = True

    try:
        try:
            VAR = value
            BLOCK
        except:
            exc = False
            exit_res = await aexit(mgr, *sys.exc_info())
            if not exit_res:
                raise

    finally:
        if exc:
            await aexit(mgr, None, None, None)


As with regular ``with`` statements it is possible to specify a list of context
managers.


It is an error to pass a regular context manager without ``__aenter__`` and
``__aexit__`` methods to ``async with``.

For example, this will make it possible to implement a proper database
transaction manager for coroutines::

    async def commit(session, data):
        ...

        async with session.transaction():
            ...
            await session.update(data)
            ...

Code that needs locking will also look lighter::

    async with lock:
        ...

instead of::

    with (yield from lock):
        ...


Asynchronous Iterators and "async for"
--------------------------------------

An asynchronous iterator will be able to call asynchronous code in its magic
**next** implementation.  We propose a new iteration protocol: an object that
supports asynchronous iteration must implement a ``__aiter__`` method, which
must in turn return an object with ``__anext__`` asynchronous method.
``__anext__`` must raise a ``StopAsyncIteration`` exception when the iteration
is over.

Since it is prohibited to have ``yield`` inside async methods, it's not
possible to create asynchronous iterators by creating a generator with both
``await`` and ``yield`` expressions.

We propose a new statement for iterating through asynchronous iterators::

    async for TARGET in ITER:
        BLOCK

which is roughly equivalent to::

    iter = (ITER)
    iter = type(iter).__aiter__(iter)
    while True:
        try:
            TARGET = await type(iter).__anext__(iter)
        except StopAsyncIteration:
            break

        BLOCK


The existing built-ins ``next()`` and ``iter()`` will not work with asynchronous
iterators.  A pair of new built-in functions ``anext()`` and ``aiter()`` will
be added.

For the sake of restricting the broadness of this PEP there is no new syntax
for asynchronous comprehensions.  This should be considered in a separate PEP.

Example: with asynchronous iteration protocol it will be possible to
asynchronously buffer data during the iteration::

    async for data in cursor:
        ...

Where ``cursor`` is an asynchronous iterator that prefetches ``N`` rows
of data after every ``N`` iterations.

The following code illustrates new asynchronous iteration protocol::

    class Cursor:
        def __init__(self):
            self.buffer = collections.deque()

        def fill_buffer(self):
            ...

        def __iter__(self):
            # You can't iterate with bare 'for in'
            raise NotImplementedError

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self.buffer:
                self.buffer = await self.fill_buffer()
                if not self.buffer:
                    raise StopAsyncIteration
            return self.buffer.popleft()

then the ``Cursor`` class can be used as follows::

    async for row in Cursor():
        print(row)

which would be equivalent to the following code::

    i = Cursor().__aiter__()
    while True:
        try:
            row = await i.__anext__()
        except StopIteration:
            break
        else:
            print(row)



Transition Plan
===============

To avoid backwards compatibility issues with *async* and *await* keywords, it
was decided to modify ``tokenizer.c`` in such a way, that it will:

 * recognize ``async def`` name tokens combination;
 * keep track of regular and async functions;
 * replace ``'async'`` token with ``ASYNC`` and ``'await'`` token with ``AWAIT``
   when in the process of yielding tokens for async functions.

This approach allows for seamless combination of new syntax features (all of
them available only in ``async`` functions) with any existing code.

There is no observable slowdown of parsing python files with the modified
tokenizer: parsing of one 12Mb file (``Lib/test/test_binop.py`` repeated 1000
times) takes the same amount of time.

Grammar changes are also fairly minimal::

    await_expr: AWAIT test
    await_stmt: await_expr

    decorated: decorators (classdef | funcdef | async_funcdef)
    async_funcdef: ASYNC funcdef

    async_stmt: ASYNC (funcdef | with_stmt) # will add for_stmt later

    compound_stmt: (if_stmt | while_stmt | for_stmt | try_stmt | with_stmt
                  | funcdef | classdef | decorated | async_stmt)

    atom: ('(' [yield_expr|await_expr|testlist_comp] ')' |
          '[' [testlist_comp] ']' |
          '{' [dictorsetmaker] '}' |
          NAME | NUMBER | STRING+ | '...' | 'None' | 'True' | 'False’)

    expr_stmt: testlist_star_expr (augassign (yield_expr|await_expr|testlist) |
                        ('=' (yield_expr|await_expr|testlist_star_expr))*)


Design Considerations
=====================

No implicit wrapping in Futures
-------------------------------

There is a proposal to add similar mechanism to [ES7]_.  A key difference
is that JavaScript async functions will always return a Promise. While this
approach has some advantages, it also implies that a new Promise object will
be created on each async function invocation.

We could implement a similar functionality in Python, by wrapping all async
functions in a Future object, but this has the following disadvantages:

1. Performance.  A new Future object will be instantiated on each coroutine
   call.  Moreover, this will make implementation of ``await`` expressions
   slower (disabling optimizations of ``yield from``).

2. A new built-in ``Future`` object will need to be added.


Reference Implementation
========================

The reference implementation can be found here: [impl]_.


References
==========

.. [asyncio]
   https://docs.python.org/3/library/asyncio.html

.. [trollius]
   https://pypi.python.org/pypi/trollius

.. [ES7]
   http://wiki.ecmascript.org/doku.php?id=strawman:async_functions

.. [script]
   https://gist.github.com/1st1/acfd5709e24cd07d9424

.. [impl]
   https://github.com/1st1/cpython/tree/await
