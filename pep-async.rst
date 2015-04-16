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
from`` syntax.  Documentation of the asyncio [1]_ module in the standard library
recommends using the ``@asyncio.coroutine`` decorator to state intent
(documentation) and ease debugging (developer efficiency).  This approach
requires users to understand generators, most importantly the difference between
``yield`` and ``yield from``. Existing Python 2-compatible third-party
frameworks, including the ``asyncio`` backport trollius [2]_, implement
coroutines using ``yield`` and trampolines, adding to the confusion.

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

The proposed syntax enhancements are not tailored to any specific library.  Any
framework that uses a concept of coroutines can benefit from this proposal.


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
object's ``tp_finalize`` implementation is tweaked to raise a
``ResourceWarning`` if the ``send`` method was never called on it (only for
functions with ``CO_ASYNC`` bit in ``co_flag``).  This is an extremely important
feature, since omitting a ``yield from`` is a common mistake.
``@asyncio.coroutine`` decorator addresses the problem by wrapping generators
with a special object in asyncio debug mode; however, we believe, that only
a small fraction of asyncio users knows about it::

    async def read():
        ...
    # later in the code:
    read() # this line raises a ResourceWarning with a pointer to this line

``StopIteration`` exceptions will not be propagated out of async functions;
instead they will be wrapped in a ``RuntimeError``.  For regular generators
such behavior requires a future import (see PEP 479), but since async functions
is a new concept, it is safe to have this feature enabled for them by default.


Await Expression
----------------

Await expression is almost a direct equivalent of ``yield from``::

    async def read_data(db):
        data = await db.fetch('SELECT ...')
        ...

It will use the ``yield from`` implementation with an extra quick step of
validating its argument.  It will only accept:

* ``async`` functions;

* generators with ``CO_ASYNC`` in their ``gi_code.co_flags``;

* objects with their ``__iter__`` method tagged with ``__async__ = True``
  attribute.  This is to enable backwards compatibility and use of bare
  ``yield`` statements to suspend code execution in a chain of ``await`` calls.
  We will call such objects as **Future-like** objects in the rest of this PEP.

It is a ``SyntaxError`` to use ``await`` outside of an ``async`` function.


Asynchronous Context Managers and "async with"
----------------------------------------------

An asynchronous Context Manager will be able to suspend execution in its
**enter** and **exit** methods.

To make it possible we propose to add a new protocol for asynchronous context
managers. Two new magic methods will be added: ``__aenter__`` and
``__aexit__``.  Both must either return a **Future-like** object, or be an
``async`` function.


New Syntax
++++++++++

We propose a new statement for asynchronous context managers::

    async with EXPR as VAR:
        BLOCK


which is roughly equivalent to::

    mgr = (EXPR)
    aexit = type(mgr).__aexit__
    aenter = type(mgr).__aenter__(mgr)
    exc = True

    try:
        try:
            VAR = await aenter
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


Example
+++++++

With async context managers it is easy to implement proper database transaction
managers for coroutines::

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
supports asynchronous iteration must implement a ``__aiter__`` asynchronous
method, which must in turn return an object with ``__anext__`` asynchronous
method. ``__anext__`` must raise a ``StopAsyncIteration`` exception when the
iteration is over.

Since it is prohibited to have ``yield`` inside async methods, it's not
possible to create asynchronous iterators by creating a generator with both
``await`` and ``yield`` expressions.


Why StopAsyncIteration?
+++++++++++++++++++++++

Async functions are still generators.  So for python, there is no
**fundamental** difference between

::

    def g1():
        yield from fut
        return 'spam'

and

::

    def g2():
        yield from fut
        raise StopIteration('spam')

and

::

    async def a1():
        await fut
        raise StopIteration('spam')

::

    async def a2():
        await fut
        return 'spam'

The only way to tell the outside code that the iteration has ended is to raise
something other than ``StopIteration``.  Therefore, a new built-in exception
class ``StopAsyncIteration`` was added.

Moreover, with semantics from PEP 479, all ``StopIteration`` exceptions raised
in async functions will be wrapped in ``RuntimeError``.


New Syntax
++++++++++

We propose a new statement for iterating through asynchronous iterators::

    async for TARGET in ITER:
        BLOCK
    else:
        BLOCK2

which is roughly equivalent to::

    iter = (ITER)
    iter = await type(iter).__aiter__(iter)
    running = True
    while running:
        try:
            TARGET = await type(iter).__anext__(iter)
        except StopAsyncIteration:
            running = False
        else:
            BLOCK
    else:
        BLOCK2


As for with regular ``for`` statement, ``async for`` will have an optional
``else`` clause.


anext() and aiter()
+++++++++++++++++++

The existing built-ins ``next()`` and ``iter()`` will not work with asynchronous
iterators.  A pair of new built-in functions ``anext()`` and ``aiter()`` will
be added.


Comprehensions
++++++++++++++

For the sake of restricting the broadness of this PEP there is no new syntax
for asynchronous comprehensions.  This should be considered in a separate PEP.


Example
+++++++

With asynchronous iteration protocol it will be possible to asynchronously
buffer data during the iteration::

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

        async def __aiter__(self):
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

    i = await Cursor().__aiter__()
    while True:
        try:
            row = await i.__anext__()
        except StopAsyncIteration:
            break
        else:
            print(row)


Transition Plan
===============

To avoid backwards compatibility issues with **async** and **await** keywords,
it was decided to modify ``tokenizer.c`` in such a way, that it will:

* recognize ``async def`` name tokens combination;

* keep track of regular and async functions;

* replace ``'async'`` token with ``ASYNC`` and ``'await'`` token with ``AWAIT``
  when in the process of yielding tokens for async functions.

This approach allows for seamless combination of new syntax features (all of
them available only in ``async`` functions) with any existing code.

An example of having "async def" and "async" attribute in one piece of code::

    class Spam:
        async = 42

    async def ham():
        print(getattr(Spam, 'async'))

    # The coroutine can be executed and will print '42'

There is no observable slowdown of parsing python files with the modified
tokenizer: parsing of one 12Mb file (``Lib/test/test_binop.py`` repeated 1000
times) takes the same amount of time.


Backwards Compatibility
-----------------------

The only backwards incompatible change is an extra argument ``is_async`` to
``FunctionDef`` AST node.  But since it is a documented fact that the structure
of AST nodes is an implementation detail and subject to change, this should not
be considered as a serious issue.


Grammar Updates
---------------

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


Transition Period Shortcomings
------------------------------

There is just one.

Until ``async`` and ``await`` are not proper keywords, it is not possible (or at
least very hard) to fix ``tokenizer.c`` to recognize them on **same line** with
``def`` keyword::

    # async and await will always be parsed as variables

    async def outer():                             # 1
        def nested(a=(await fut)):
            pass

    async def foo(): return (await fut)            # 2

Since ``await`` and ``async`` in such cases are parsed as ``NAME`` tokens, a
``SyntaxError`` will be raised.

The above examples, however, are hard to parse for humans too, and can be easily
rewritten to a more readable form::

    async def outer():                             # 1
        a_default = await fut
        def nested(a=a_default):
            pass

    async def foo():                               # 2
        return (await fut)


Deprecation Plans
-----------------

``async`` and ``await`` names will be softly deprecated in CPython 3.5 and 3.6,
and in 3.7 we may consider transforming them to proper keywords.  Making them
proper keywords before 3.7 might make it harder for people to port their code
to Python 3.


types.async_def()
----------------

A new function will be added to the ``types`` module: ``async_def(gen)``.  It
will apply ``CO_ASYNC`` bit to the passed generator's code object, so that it
can be awaited on in async functions.  This is to enable an easy upgrade path
for existing libraries.


asyncio
-------

``asyncio`` module will be adapted and tested to work with async functions and
new statements.  Backwards compatibility will be 100% preserved.

The required changes are mainly:

1. Modify ``@asyncio.coroutine`` decorator to use new ``types.async_def()``
   function on all wrapped generators.

2. Add ``__async__ = True`` attribute to ``asyncio.Future.__iter__`` method.


Design Considerations
=====================

No implicit wrapping in Futures
-------------------------------

There is a proposal to add similar mechanism to ECMAScript 7 [3]_.  A key
difference is that JavaScript async functions will always return a Promise.
While this approach has some advantages, it also implies that a new Promise
object will be created on each async function invocation.

We could implement a similar functionality in Python, by wrapping all async
functions in a Future object, but this has the following disadvantages:

1. Performance.  A new Future object would be instantiated on each coroutine
   call.  Moreover, this will make implementation of ``await`` expressions
   slower (disabling optimizations of ``yield from``).

2. A new built-in ``Future`` object would need to be added.


Why "__aiter__" is async
------------------------

In principle, ``__aiter__`` could be a regular function.  There are several
good reasons to make it ``async``:

* as most of the ``__a*__`` methods are ``async``, users would often make
  a mistake defining it as ``async`` anyways;

* there might be a need to run some asynchronous operations in ``__aiter__``,
  for instance to prepare DB queries or do some file operation.


Importance of "async" keyword
-----------------------------

While it is possible to just implement ``await`` expression and treat all
functions with at least one ``await`` as async functions, this approach will
make APIs design, code refactoring and its long time support harder.

Let's pretend that Python only has ``await`` keyword::

    def useful():
        ...
        await log(...)
        ...

    def important():
        await useful()

If ``useful()`` method is refactored and someone removes all ``await``
expressions from it, it would become a regular python function, and all code
that depends on it, including ``important()`` will be broken.  To mitigate this
issue a decorator similar to ``@asyncio.coroutine`` has to be introduced.

Also, async/await is not a new concept in programming languages.  C# has had
it for years, and there are proposals to add them in JavaScript and C++.


Why "async def"
---------------

For some people bare ``async name(): pass`` syntax might look more appealing
than ``async def name(): pass``.  It is certainly easier to type.  But on the
other hand, it breaks the symmetry between ``async def``, ``async with`` and
``async for``, where ``async`` is a modifier, stating that the statement is
asynchronous.  It is also more consistent with the existing grammar.


Why not a "future" import
-------------------------

"Future" imports are inconvenient and easy to forget to add.  Also, they are
enabled for the whole source file.  Consider that there is a big project with a
popular module named "async.py".  With future imports it will be required to
either import it using ``__import__()`` or ``importlib.import_module()`` calls,
or to rename the module.  The proposed approach makes it possible to continue
using old code and modules without a hassle, while coming up with a migration
plan for future python versions.


Why magic methods start with "a"
--------------------------------

New async magic methods ``__aiter__``, ``__anext__``, ``__aenter__``, and
``__aexit__`` all start with the same prefix "a".  An alternative proposal is to
use "async" suffix, so that ``__aiter__`` would be ``__async_iter__``.  However,
to align new magic methods with the existing ones, such as ``__radd__`` and
``__iadd__`` it was decided to use a shorter version.


Why not reuse existing magic names
----------------------------------

An alternative idea about new async iterators and context managers was to re-use
existing magic methods, by adding an ``async`` keyword to their declarations::

    class CM:
        async def __enter__(self): # instead of __aenter__
            ...

This approach has the following downsides:

* it is not possible to create an object that works in both ``with`` and
  ``async with`` statements;

* it looks confusing and would require some implicit magic behind the scenes in
  the interpreter;

* one of the main points of this proposal is to make async functions as simple
  and fool-proofed as possible.


Performance
===========

async/await
-----------

We used the following simple micro-benchmark to determine performance difference
between "async" functions and generators::

    import sys
    import time

    def binary(n):
        if n <= 0:
            return 1
        l = yield from binary(n - 1)
        r = yield from binary(n - 1)
        return l + 1 + r

    async def abinary(n):
        if n <= 0:
            return 1
        l = await abinary(n - 1)
        r = await abinary(n - 1)
        return l + 1 + r

    def timeit(gen, depth, repeat):
        t0 = time.time()
        for _ in range(repeat):
            list(gen(depth))
        t1 = time.time()
        print('{}({}) * {}: total {:.3f}s'.format(
            gen.__name__, depth, repeat, t1-t0))

The result is that there is no observable performance difference.  Here's an
example run (note that depth of 19 means 1,048,575 calls):

::

    abinary(19) * 30: total 13.156s
    binary(19) * 30: total 13.081s
    abinary(19) * 30: total 12.984s
    binary(19) * 30: total 13.183s
    abinary(19) * 30: total 12.985s
    binary(19) * 30: total 12.953s


Reference Implementation
========================

The reference implementation can be found here: [4]_.


References
==========

.. [1] https://docs.python.org/3/library/asyncio.html

.. [2] https://pypi.python.org/pypi/trollius

.. [3] http://wiki.ecmascript.org/doku.php?id=strawman:async_functions

.. [4] https://github.com/1st1/cpython/tree/await
