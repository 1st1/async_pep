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
frameworks, such as Twisted [12]_, Tornado [13]_, and many others, including the
``asyncio`` backport trollius [2]_, implement coroutines using ``yield`` and
trampolines, adding to the confusion.

This proposal makes coroutines a first class construct in Python to clearly
separate them from generators.  This allows unambiguous usage of generators and
coroutines in the same source file, as well as helps to avoid calling generators
from coroutines and vice-versa.  It also enables linters and IDEs to improve
static code analysis and refactoring.

Introducing the ``async`` keyword enables creation of asynchronous context
managers and iteration protocols.  The former lets Python perform non-blocking
operations upon entering and exiting the context manager, while the latter lets
Python perform non-blocking operations during iteration steps (in an equivalent
of ``__next__()``).


Specification
=============

The proposed syntax enhancements are not tailored to any specific library.  Any
framework that uses a concept of coroutines can benefit from this proposal.

It is required that the reader clearly understands how ``yield`` and ``yield
from`` work (PEP 380).  It is also recommended to read PEP 3156 (asyncio
framework.)


New Coroutines Declaration Syntax
---------------------------------

Use ``async`` and ``def`` keywords to declare a coroutine ("async function"
later in this PEP, to avoid confusion)::

    async def read_data(db):
        ...

Some key properties of async functions:

* Async functions are always generators, even if they do not contain ``await``
  expressions.

* It is a syntax error to have ``yield`` or ``yield from`` expressions in
  ``async`` function.

* A new bit flag ``CO_ASYNC`` for code object's ``co_flag`` field will be
  introduced to allow runtime detection of async functions (and migrating
  existing code).  All async functions have both ``CO_ASYNC`` and
  ``CO_GENERATOR`` bits set.

* ``StopIteration`` exceptions will not be propagated out of async functions;
  instead they will be wrapped in a ``RuntimeError``.  For regular generators
  such behavior requires a future import (see PEP 479), but since async
  functions is a new concept, it is safe to have this feature enabled for them
  by default.


Await Expression
----------------

Await expression is almost a direct equivalent of ``yield from``::

    async def read_data(db):
        data = await db.fetch('SELECT ...')
        ...

``await`` suspends the ``read_data`` function until ``db.fetch`` async function
or future-like object completes and returns the result data.

It will use the ``yield from`` implementation with an extra quick step of
validating its argument.  It will only accept:

* ``async def`` functions.

* generators with ``CO_ASYNC`` in their ``gi_code.co_flags`` (see
  ``types.async_def()`` later in this PEP).  This is to make all existing
  coroutines in asyncio compatible with the new proposal.

* objects with an ``__await__`` method that returns an iterator.

  Any ``yield from`` in asyncio ends up at some ``yield``.  This is a
  fundamental mechanism of how Futures must be implemented.  Since async
  functions are special kind of generators, every ``await`` will be suspended by
  a ``yield`` somewhere down the chain of ``await`` calls (please refer to PEP
  3156 for detailed explanation.)

  To enable this behavior for async functions, a new magic method called
  ``__await__`` will be added.  For asyncio, for instance, to enable Future
  objects in ``await`` statements, the only change is to add ``__await__ =
  __iter__`` line to the Future class.

  Objects with ``__await__`` method will be called **Future-like** objects in
  the rest of this PEP.

  Also, please note that ``__aiter__`` method (see its definition below) cannot
  be used for this purpose.  It is a different protocol, and would be like using
  ``__iter__`` instead of ``__call__`` for regular callables.

It is a ``SyntaxError`` to use ``await`` outside of an ``async`` function.


Asynchronous Context Managers and "async with"
----------------------------------------------

An asynchronous Context Manager will be able to suspend execution in its
**enter** and **exit** methods.

To make it possible  new protocol for asynchronous context managers is proposed.
Two new magic methods will be added: ``__aenter__`` and ``__aexit__``.  Both
must either return a **Future-like** object, or be an ``async`` function.


New Syntax
++++++++++

A new statement for asynchronous context managers is proposed::

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


As with regular ``with`` statements it is possible to specify multiple context
managers in one ``async with`` statement.


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
**next** implementation.  A new iteration protocol is proposed: an object that
supports asynchronous iteration must implement a ``__aiter__`` asynchronous
method, which must in turn return an object with ``__anext__`` asynchronous
method. ``__anext__`` must raise a ``StopAsyncIteration`` exception when the
iteration is over.

Since it is prohibited to have ``yield`` inside async functions, it's not
possible to create asynchronous iterators by creating a generator with both
``await`` and ``yield`` expressions.


Why StopAsyncIteration?
+++++++++++++++++++++++

Async functions are still generators.  So before PEP 479, there was no
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

And since PEP 479 is accepted and enabled by default for async functions, the
following example will have its ``StopIteration`` wrapped into a
``RuntimeError``

::

    async def a1():
        await fut
        raise StopIteration('spam')

The only way to tell the outside code that the iteration has ended is to raise
something other than ``StopIteration``.  Therefore, a new built-in exception
class ``StopAsyncIteration`` was added.

Moreover, with semantics from PEP 479, all ``StopIteration`` exceptions raised
in async functions will be wrapped in ``RuntimeError``.


New Syntax
++++++++++

A new statement for iterating through asynchronous iterators is proposed::

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


Comprehensions
++++++++++++++

For the sake of restricting the broadness of this PEP there is no new syntax
for asynchronous comprehensions.  This should be considered in a separate PEP.


Example 1
+++++++++

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

        def _prefetch(self):
            ...

        async def __aiter__(self):
            return self

        async def __anext__(self):
            if not self.buffer:
                self.buffer = await self._prefetch()
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


Example 2
+++++++++

The following is a utility class that transforms a regular iterator to
asynchronous one.  While this is not a very useful thing to do, the code
illustrates the relationship between regular and asynchronous iterators.

::

    class AsyncIteratorWrapper:
        def __init__(self, obj):
            self._it = iter(obj)

        async def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                value = next(self._it)
            except StopIteration:
                raise StopAsyncIteration
            return value

    data = "abc"
    it = AsyncIteratorWrapper("abc")
    async for item in it:
        print(it)


Debugging Features
------------------

One of the most frequent mistakes that people make when using generators as
coroutines is forgetting to use ``yield from``::

    @asyncio.coroutine
    def useful():
        asyncio.sleep(1) # this will do noting without 'yield from'

For debugging this kind of mistakes there is a special debug mode in asyncio,
in which ``@coroutine`` decorator wraps all functions with a special object
with overloaded ``__del__``.  Whenever a wrapped generator gets garbage
collected, a detailed logging message is generated with information about where
exactly the decorator function was defined, stack trace of where it was
collected, etc.  Wrapper object also provides a convenient ``__repr__`` function
with detailed information about the generator.

The only problem is how to enable these debug capabilities.  Since debug
facilities should be a no-op in production mode, ``@coroutine`` decorator makes
the decision of whether to wrap or not to wrap based on an OS environment
variable ``PYTHONASYNCIODEBUG``.  This way it is possible to run asyncio
programs with asyncio's own functions instrumented.  ``EventLoop.set_debug``, a
different debug facility, has no impact on ``@coroutine`` decorator's behavior.

With this proposal, async functions is a native, distinct from generators,
concept.  A new method ``set_async_wrapper`` will be added to the ``sys``
module, with which frameworks can provide advanced debugging facilities.

It is also important to make async functions as fast and efficient as possible,
therefore there are no debug features enabled by default.

Example::

    async def debug_me():
        await asyncio.sleep(1)

    def async_debug_wrap(generator):
        return asyncio.AsyncDebugWrapper(generator)

    sys.set_async_wrapper(async_debug_wrap)

    debug_me()  # <- this line will likely GC the decorator object and
                # trigger AsyncDebugWrapper's code.

    assert isinstance(debug_me(), AsyncDebugWrapper)

    sys.set_async_wrapper(None)   # <- this unsets any previously set wrapper
    assert not isinstance(debug_me(), AsyncDebugWrapper)


List of functions and methods
=============================

================= =======================================  =================
Method            Can contain                              Can't contain
================= =======================================  =================
async def func    await, return value                      yield, yield from
async def __a*__  await, return value                      yield, yield from
def __a*__        return Future-like                       await
def __await__     yield, yield from, return iterable       await
generator         yield, yield from, return                await
================= =======================================  =================

Where:

* ""async def func": async function;

* "async def __a*__": ``__aiter__``, ``__anext__``, ``__aenter__``,
  ``__aexit__`` defined with the ``async`` keyword;

* "def __a*__": ``__aiter__``, ``__anext__``, ``__aenter__``, ``__aexit__``
  defined without the ``async`` keyword, must return a Future-like object;

* "def __await__": ``__await__`` method to implement Future-like objects;

* generator: a "regular" generator, function defined with ``def`` and which
  contains a least one ``yield`` or ``yield from`` expression.

**Future-like** is an object with an ``__await__`` method.


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


Backwards Compatibility
-----------------------

The only backwards incompatible change is an extra argument ``is_async`` to
``FunctionDef`` AST node.  But since it is a documented fact that the structure
of AST nodes is an implementation detail and subject to change, this should not
be considered a serious issue.


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
least very hard) to fix ``tokenizer.c`` to recognize them on the **same line**
with ``def`` keyword::

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

This limitation will go away as soon as ``async`` is a proper keyword.


Deprecation Plans
-----------------

``async`` and ``await`` names will be softly deprecated in CPython 3.5 and 3.6.
In 3.7 we will transform them to proper keywords.  Making ``async`` and
``await`` proper keywords before 3.7 might make it harder for people to port
their code to Python 3.


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
   function on all wrapped functions.

2. Add ``__await__ = __iter__`` line to ``asyncio.Future`` class.


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

3. Coming up with a generic ``Future`` interface that is usable for any use case
   in any framework is a very hard to solve problem.

4. It is not a feature that is used frequently, when most of your code is
   coroutines.


Why "async" and "await" keywords
--------------------------------

async/await is not a new concept in programming languages:

* C# has it since long time ago [6]_;

* proposal to add async/await in ECMAScript 7 [3]_;
  see also Traceur project [10]_;

* Facebook's Hack/HHVM [7]_;

* Google's Dart language [8]_;

* Scala [9]_;

* proposal to add async/await to C++ [11]_;

* and many other less popular languages.

This is a huge benefit, as some users already have experience with async/await,
and because it makes working with many languages in one project easier (Python
with ECMAScript 7 for instance).


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

If ``useful()`` function is refactored and someone removes all ``await``
expressions from it, it would become a regular python function, and all code
that depends on it, including ``important()`` will be broken.  To mitigate this
issue a decorator similar to ``@asyncio.coroutine`` has to be introduced.


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
use "async" prefix, so that ``__aiter__`` becomes ``__async_iter__``.  However,
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

Overall Impact
--------------

This proposal introduces no observable performance impact.  Here is an output
of python's official set of benchmarks [5]_:

::

    python3 perf.py -r -b default ../cpython/python.exe ../cpython-git/python.exe

    [skipped]

    Report on Darwin ysmac 14.3.0 Darwin Kernel Version 14.3.0:
    Mon Mar 23 11:59:05 PDT 2015; root:xnu-2782.20.48~5/RELEASE_X86_64
    x86_64 i386

    Total CPU cores: 8

    ### etree_iterparse ###
    Min: 0.365359 -> 0.349168: 1.05x faster
    Avg: 0.396924 -> 0.379735: 1.05x faster
    Significant (t=9.71)
    Stddev: 0.01225 -> 0.01277: 1.0423x larger

    The following not significant results are hidden, use -v to show them:
    django_v2, 2to3, etree_generate, etree_parse, etree_process, fastpickle,
    fastunpickle, json_dump_v2, json_load, nbody, regex_v8, tornado_http.


Tokenizer modifications
-----------------------

There is no observable slowdown of parsing python files with the modified
tokenizer: parsing of one 12Mb file (``Lib/test/test_binop.py`` repeated 1000
times) takes the same amount of time.


async/await
-----------

The following micro-benchmark was used to determine performance difference
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

List of high-level changes
--------------------------

1. New syntax for defining async functions: ``async def`` and new ``await``
   keyword.

2. New ``__await__`` method for Future-like objects.

3. New syntax for async context managers: ``async with``.  And associated
   protocol with ``__aenter__`` and ``__aexit__`` methods.

4. New syntax for async iteration: ``async for``.  And associated protocol
   with ``__aiter__``, ``__aexit__`` and new built-in exception
   ``StopAsyncIteration``.

5. New AST nodes: ``AsyncFor``, ``AsyncWith``, ``Await``; ``FunctionDef`` AST
   node got a new argument ``is_async``.

6. New functions: ``sys.set_async_wrapper(callback)`` and
   ``types.async_def(gen)`` function.

7. New ``CO_ASYNC`` bit flag for code objects.

While the list of changes and new things is not short, it is important to
understand, that most users will not use these features directly.  It is
intended to be used in frameworks and libraries to provide users with convenient
to use and unambiguous APIs with ``async def``, ``await``, ``async for`` and
``async with`` syntax.


Working example
---------------

All concepts proposed in this PEP are implemented [4]_ and can be tested.  The
implementation is **not** production ready!

::

    import asyncio


    async def echo_server():
        print('Serving on localhost:8000')
        await asyncio.start_server(handle_connection, 'localhost', 8000)


    async def handle_connection(reader, writer):
        print('New connection...')

        while True:
            data = await reader.read(8192)

            if not data:
                break

            print('Sending {:.10}... back'.format(repr(data)))
            writer.write(data)


    loop = asyncio.get_event_loop()
    loop.run_until_complete(echo_server())
    try:
        loop.run_forever()
    finally:
        loop.close()


References
==========

.. [1] https://docs.python.org/3/library/asyncio.html

.. [2] https://pypi.python.org/pypi/trollius

.. [3] http://wiki.ecmascript.org/doku.php?id=strawman:async_functions

.. [4] https://github.com/1st1/cpython/tree/await

.. [5] https://hg.python.org/benchmarks

.. [6] https://msdn.microsoft.com/en-us/library/hh191443.aspx

.. [7] http://docs.hhvm.com/manual/en/hack.async.php

.. [8] https://www.dartlang.org/articles/await-async/

.. [9] http://docs.scala-lang.org/sips/pending/async.html

.. [10] https://github.com/google/traceur-compiler/wiki/LanguageFeatures#async-functions-experimental

.. [11] http://www.open-std.org/jtc1/sc22/wg21/docs/papers/2013/n3722.pdf (PDF)

.. [12] https://twistedmatrix.com/trac/

.. [13] http://www.tornadoweb.org/en/stable/
