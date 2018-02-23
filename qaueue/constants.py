__all__ = [
    'colors',
    'fields',
    'item_types',
    'statuses',
]

class _constant(object):
    @classmethod
    def keys(cls):
        import re
        return filter(lambda i: re.match('^[A-Z_]+$', i) is not None, dir(cls))

    @classmethod
    def values(cls):
        return map(lambda attr: getattr(cls, attr), cls.keys())

    @classmethod
    def items(cls):
        return map(lambda attr: (attr, getattr(cls, attr)), cls.keys())


class colors(_constant):
    RED = '#F61A1A'
    GREEN = '#0BBF0B'
    BLUE = '#3AA3E3'
    YELLOW = '#E6F316'
    ORANGE = '#FD8600'


class fields(_constant):
    STATUS = 'status'
    VALUE = 'value'
    TYPE = 'type'
    NAME = 'name'
    URL = 'url'
    RELEASED_AT = 'released_at'

    # @classmethod
    # def list(cls):
    #     return [
    #         cls.STATE,
    #         cls.VALUE,
    #         cls.TYPE,
    #         cls.NAME,
    #         cls.URL,
    #         cls.RELEASED_AT,
    #     ]


class statuses(_constant):
    INITIAL = 'queued'
    COMPLETED = 'released'


class item_types(_constant):
    PIVOTAL_STORY = 'pivotal_story'
    GITHUB_PUlL_REQUEST = 'github_pr'
    OTHER = 'other'
