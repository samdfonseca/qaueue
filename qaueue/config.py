import os
import typing

from .colors import colors

class Config(object):
    REDIS_ADDRESS = os.environ.get('REDIS_ADDRESS', 'redis://localhost')
    REDIS_DB = int(os.environ.get('REDIS_DB', 1))
    SLACK_VERIFICATION_TOKEN = os.environ.get('SLACK_VERIFICATION_TOKEN')
    ENABLED_CHANNEL_COMMANDS = {
            'qa-talk': '*',
            '*': ['help', 'list'],
            }
    STATE_COLORS = {
            'integration': colors.ORANGE,
            'staging': colors.YELLOW,
            'released': colors.GREEN,
            'queued': colors.BLUE,
            '*': colors.BLUE,
            }
    PIVOTAL_API_TOKEN = os.environ.get('PIVOTAL_API_TOKEN')
    PIVOTAL_PROJECT_IDS = os.environ.get('PIVOTAL_PROJECT_IDS', '').split(',')
    GITHUB_ACCESS_TOKEN = os.environ.get('GITHUB_ACCESS_TOKEN')

    @classmethod
    def channel_command_enabled(cls, channel: str, command: str) -> bool:
        enabled_channel_commands = cls.ENABLED_CHANNEL_COMMANDS.get(channel,
                cls.ENABLED_CHANNEL_COMMANDS.get('*'))
        return (enabled_channel_commands == '*' or command in enabled_channel_commands)

    @classmethod
    def get_channels_command_enabled(cls, command: str) -> typing.List[str]:
        return [k for k, v in cls.ENABLED_CHANNEL_COMMANDS.items() if (command in v or v == '*')]

    @classmethod
    def get_state_color(cls, state: str) -> str:
        return cls.STATE_COLORS.get(state, cls.STATE_COLORS['*'])
