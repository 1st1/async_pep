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

This PEP introduces a new syntax for coroutines, asynchronous with statements
and for loops.  The main motivation behind this proposal is to streamline
writing and maintaining asynchronous code, as well as to simplify previously
hard to implement code patterns.


Rationale and Goals
===================

As of now, coroutines in python are usually implemented using generators and
``yield from`` syntax. Documentation of standard library module [asyncio]_ also
recommends using ``\@asyncio.coroutine`` decorator for documentation and better
code readability purposes.  While this approach works fairly well, it requires
users to understand generators, such as difference between ``yield`` and ``yield
from``. Also, many frameworks still implement coroutines with ``yield`` and
trampolines, which is a much slower approach.

This proposal aims at making coroutines a first class construct in Python to
clearly separate generators from coroutines.  This will allow unambiguous usage
of generators in coroutines close to each other, but avoid intermixing them by
mistake.  It should also help linters and IDEs to improve code static analysis
and refactoring.

The other side of this proposal is to enable asynchronous context managers and
iteration protocol.  For example, it is impossible to implement a context
manager that blocks in its ``__exit__`` method, or to have an iterator over
database cursor that prefetches data asynchronously as you iterate over it.


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

A new bit flag for ``co_flag`` field of code objects will be introduced to allow
runtime detection of coroutine objects.


Await Expression
----------------

Await expression is almost a direct equivalent of ``yield from``::

    async def read_data(db):
        data = await db.fetch('SELECT ...')
        ...

It will share most of the ``yield from`` implementation with an extra step of
validating its argument.  Only ``async`` functions and `asynchronous iterators`_
(with a ``__aiter__`` method) will be accepted.

It is a ``SyntaxError`` to use ``await`` outside of an ``async`` function.


Asynchronous Context Managers
-----------------------------

An asynchronous Context Manager will be able to suspend execution in its *enter*
and *exit* methods.

To make it possible we propose to add a new protocol for asynchronous context
managers. Two new dunder methods will be added: ``__aenter__`` and
``__aexit__``.  Both must either return an `asynchronous iterator`_, or be an
``async`` function.

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

    with (yield lock):
        ...


Asynchronous Iterators
----------------------

An asynchronous iterator will be able to call asynchronous code in its *next*
implementation.  We propose a new iteration protocol: an object that supports
asynchronous iteration must implement a ``__aiter__`` method, which must
in turn return an object with ``__anext__`` method.

With asynchronous iteration protocol it will be possible to asynchronously
fetch data during the iteration:

    async for data in cursor:
        ...

Where ``cursor`` is an asynchronous iterator that prefetches ``N`` rows
of data after every ``N`` iterations.


Transition Plan
===============

The feature will be enabled by future import in CPython 3.5::

    from __future__ import async_await

In CPython 3.6 the feature will be enabled by default.


Keywords occurrence in existing code
------------------------------------

As of April 9, 2015; 'master' branches:

 Project                | "await" names   | "async" names
 -----------------------+-----------------+---------------------
 Standard Library       | 0               | 32 (asyncio mostly)
 Tornado                | 0               | 1 (asyncio func)
 Django                 | 0               | 0
 Flask                  | 0               | 0
 Celery                 | 0               | 15 (module name)
 Werkzeug               | 0               | 0
 Gevent                 | 0               | 8 (class attribute)
 Gunicorn               | 0               | 6 (module name)

A script to conveniently examine code for 'async' and 'await' names
usage can be found here: [script]_.

To avoid problems with *async* keyword, we propose to modify tokenizer to treat
``async def``, ``async for`` and ``async with`` as one token. This is a viable
strategy since *async* is a modifier keyword and shouldn't be ever used without
a keyword immediately following it.


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


References
==========

.. [asyncio]
   https://docs.python.org/3/library/asyncio.html

.. [ES7]
   http://wiki.ecmascript.org/doku.php?id=strawman:async_functions

.. [script]
   https://gist.github.com/1st1/acfd5709e24cd07d9424
