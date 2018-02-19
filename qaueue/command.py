from functools import wraps
import logging
import os
import typing

from .config import Config

from aiohttp import web
import aioredis


CommandFunc = typing.Callable[[aioredis.Redis, dict, Config], web.Response]


class DuplicateCommandError(Exception):
    pass


class DuplicateDefaultCommandError(Exception):
    pass


class ArgTypeAnnotationMismatchError(Exception):
    def __init__(self, arg_name, expected_type, actual_type):
        msg = (f'''Expected '{arg_name}' to be an instance of '{expected_type}'. '''
               f'''Given '{arg_name}' is an instance of '{actual_type}\'''')
        super().__init__(msg)



class Commands(object):
    _data = {}
    _default: str = None
    
    def __init__(self, **kwargs):
        self._kwargs = kwargs

    @classmethod
    def add(cls, command: str, func: CommandFunc, default: bool = False):
        if command in cls._data:
            raise DuplicateCommandError(f'More than one function mapped to \'{command}\' command')
        if cls._default is not None and default is True:
            raise DuplicateDefaultCommandError('More than one function is marked as default')
        cls._data[command] = func
        if default is True:
            cls._default = command

    def get(self, command, default: str = None) -> CommandFunc:
        default = default or self._default
        func = self._data.get(command, self._data.get(default))
        def wrapper():
            args = []
            for arg_name, arg_type in func.__annotations__.items():
                if arg_name == 'return':
                    continue
                arg = self._kwargs.get(arg_name)
                # if not isinstance(arg, arg_type):
                #     raise ArgTypeAnnotationMismatchError(arg_name, arg_type, type(arg))
                args.append(arg)
            return func(*args)
        return wrapper


    def __iter__(self):
        return map(lambda i: i, self._data.keys())

    def default(self) -> typing.Tuple[str, CommandFunc]:
        if self._default is not None:
            return self._data.get(self._default)


def qaueue_command(command: str, default: bool = False):
    def decorator(func: CommandFunc):
        Commands.add(command, func, default)
        @wraps(func)
        def wrapper(*args, **kwargs):
            logger = logging.getLogger(f'{command}:{func.__name__}')
            args_str = ', '.join(args)
            kwargs_str = ', '.join([f'{k}={v}' for k, v in kwargs.items()])
            full_args_str = ', '.join([args_str, kwargs_str])
            logger.debug(f'Args: {full_args_str}')
            return func(*args, **kwargs)
        return wrapper
    return decorator

