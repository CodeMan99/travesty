'''
Some tools for aggregating error messages.

These solve the problem where you wish to perform a number of subtasks,
continuing if any of the fail, and you want to aggregate all the errors
generated while doing this.

One use case for this is in form validation with human-readable output. A
simple, pythonic validation function would iterate over the fields in the form,
and would raise an exception as soon as it found any field that wasn't valid.
But when the errors are displayed to the user, you will likely want to show ALL
the errors on the form, not just the first one found.

So instead, you want to validate each field of the form regardless of whether or
not the previous fields were valid, and collect a list of all the errors that
came up, so that you can show them all to the user.

If the form has three fields called 'foo', 'bar', and 'baz', then you would want
to generate an exception with three sub-entries - one for each of these fields -
plus a list of any errors that are not specific to one field, such as violating
a constraint involving two fields' values.

The ErrorAggregator class provides tools for doing this, and the NestedException
class defines an Exception subclass well-suited to storing these errors.

'''

from contextlib import contextmanager
from collections import OrderedDict


class NestedException(Exception):
    '''Exception with sub-exceptions.

    A NestedException has two useful fields, own_errors and sub_errors.

    own_errors is a list of root errors raised during some operation.

    sub_errors is a mapping from strings to NestedExceptions, representing the
    exceptions generated by named sub-steps in the operation.

    >>> e = NestedException()
    >>> print(e)
    <no message>
    >>> print(repr(e))
    NestedException([], OrderedDict())
    >>> raise e
    Traceback (most recent call last):
        ...
    NestedException: <no message>
    >>> bool(e)
    False
    >>> 'Yes' if e else 'No'
    'No'

    >>> e = NestedException()
    >>> e.add_own(ValueError('The value is wrong',))
    >>> print(e)
    The value is wrong
    >>> print(repr(e))
    NestedException([ValueError('The value is wrong',)], OrderedDict())
    >>> raise e
    Traceback (most recent call last):
        ...
    NestedException: The value is wrong
    >>> bool(e)
    True
    >>> 'Yes' if e else 'No'
    'Yes'

    >>> e.add_own(TypeError('Why would you use this type?'))
    >>> print(e)
    The value is wrong, Why would you use this type?
    >>> print(repr(e))
    NestedException([ValueError('The value is wrong',), TypeError('Why would you use this type?',)], OrderedDict())
    >>> raise e
    Traceback (most recent call last):
        ...
    NestedException: The value is wrong, Why would you use this type?

    >>> e = NestedException()
    >>> e.add_own(ValueError('The value is wrong',))
    >>> e.add_sub("foo", ValueError("foo is also wrong"))
    >>> print(e)
    The value is wrong; foo: [foo is also wrong]
    >>> print(e[0])
    The value is wrong
    >>> print(e['foo'])
    foo is also wrong
    >>> raise e
    Traceback (most recent call last):
        ...
    NestedException: The value is wrong; foo: [foo is also wrong]

    The add_own function can also take a full NestedException, in which case it
    the new exception will be merged into this one:

    >>> e2 = NestedException()
    >>> e2.add_own(ValueError("Alternate value problem"))
    >>> e2.add_sub("foo", TypeError("The type of foo is terrible!"))
    >>> e2.add_sub("bar", BufferError("bar failed."))
    >>> e.add_own(e2)
    >>> print(e)
    The value is wrong, Alternate value problem; bar: [bar failed.], foo: [foo is also wrong, The type of foo is terrible!]

    The .own_str() helper method returns a string representation of ONLY this
    error's messages:

    >>> print(e.own_str())
    The value is wrong, Alternate value problem

    >>> print(NestedException().own_str())
    <no message>

    '''
    def __init__(self):
        self.own_errors = []
        self.sub_errors = OrderedDict()
        super(NestedException, self).__init__()

    def __nonzero__(self):
        return bool(self.own_errors) or bool(self.sub_errors)

    def __bool__(self): # pragma: no cover
        return self.__nonzero__()

    def __getitem__(self, item):
        if isinstance(item, int):
            return self.own_errors[item]
        return self.sub_errors[item]

    def add_own(self, exc):
        '''Add an exception to this element.'''
        if isinstance(exc, NestedException):
            self.merge(exc)
        else:
            self.own_errors.append(exc)

    def add_sub(self, key, exc):
        '''Add a sub-exception.'''
        self.sub_errors.setdefault(key, type(self)()).add_own(exc)

    def merge(self, other):
        '''Merge another NestedException into this one.'''
        for own in other.own_errors:
            self.add_own(own)
        for key, sub in other.sub_errors.items():
            self.add_sub(key, sub)

    def own_str(self):
        '''String representation of our own errors but not sub errors.'''
        if len(self.own_errors) == 0:
            return "<no message>"
        return ', '.join(str(err) for err in self.own_errors)

    def __repr__(self):
        return 'NestedException({!r}, {!r})'.format(self.own_errors, self.sub_errors)

    def __str__(self):
        n_own = len(self.own_errors)
        n_sub = len(self.sub_errors)
        if n_own+n_sub == 0:
            return "<no message>"
        own = ', '.join(str(err) for err in self.own_errors)
        other = ', '.join('{0}: [{1}]'.format(key, str(err))
                          for (key, err) in sorted(self.sub_errors.items()))
        return '; '.join(x for x in [own, other] if x)


class ErrorAggregator(object):
    '''Helper class for trying several things and accumulating all errors.

    The class attribute error_type specifies the type of error used internally,
    which should be NestedException or a subclass thereof. The catch_type class
    attribute specifies which exceptions should be caught by the aggregator; by
    default all exceptions are caught.

    Basic usage:
    >>> eg = ErrorAggregator()
    >>> eg.own_error(Exception("something_wrong"))
    >>> with eg.checking():
    ...     raise ValueError("Too many prices")
    >>> with eg.checking_sub("x"):
    ...     raise Exception("x_failed")
    >>> eg.has_errors()
    True
    >>> eg.error.own_errors
    [Exception('something_wrong',), ValueError('Too many prices',)]
    >>> eg.error.sub_errors
    OrderedDict([('x', NestedException([Exception('x_failed',)], OrderedDict()))])

    If autoraise is True, then instead of aggregating it will raise an error as
    soon as one is added:

    >>> eg = ErrorAggregator(autoraise=True)
    >>> eg.own_error(Exception("something_wrong"))
    Traceback (most recent call last):
        ...
    NestedException: something_wrong
    >>> with eg.checking_sub('foo'):
    ...     raise ValueError("Everything is terrible")
    Traceback (most recent call last):
        ...
    NestedException: something_wrong; foo: [Everything is terrible]

    Otherwise, you should call .raise_if_any() to trigger the joint exception:
    >>> e = ErrorAggregator()
    >>> e.raise_if_any()
    >>> e.own_error(Exception("unmitigated_catastrophe"))
    >>> e.raise_if_any()
    Traceback (most recent call last):
        ...
    NestedException: unmitigated_catastrophe


    '''
    error_type = NestedException
    catch_type = Exception

    def __init__(self, autoraise=False):
        self.error = self.error_type()
        self.autoraise = autoraise

    def own_error(self, err):
        '''Add a self-error.'''
        self.error.add_own(err)
        if self.autoraise:
            raise self.error

    def sub_error(self, key, err):
        '''Add a child-error.'''
        self.error.add_sub(key, err)
        if self.autoraise:
            raise self.error

    @contextmanager
    def checking(self):
        '''Context manager for try-excepting tasks.'''
        try:
            yield
        except self.catch_type as e:
            self.own_error(e)

    @contextmanager
    def checking_sub(self, key):
        '''Context manager for try-excepting subtasks.'''
        try:
            yield
        except self.catch_type as e:
            self.sub_error(key, e)

    def has_errors(self):
        '''Returns true if the aggregator holds any errors.'''
        return bool(self.error)

    def raise_if_any(self):
        '''If the aggregator has any exceptions, raise a NestedException'''
        if self.has_errors():
            raise self.error

