import asyncio
import itertools
import os
import signal
from typing import Any


class Shell:
    colors = {'route': 33, 'module': 34, 'schema': 35, 'field': 96}

    def capitalize(self, text: str) -> str:
        i = 0
        line = ''
        if ord(text[0]) == 27:
            for i, char in enumerate(text):
                line += char
                if char == 'm':
                    i += 1
                    break

        line += text[i].upper()
        line += text[(i+1):]
        return line

    def get_entry_text(self, text: str) -> str:
        tint = self.colors.get(text)
        return '\033[1;{}m{}\033[0m'.format(tint, text)

    def get_input_schema_text(self, flag: bool) -> str:
        return '\033[0;90m[{}]\033[0m'.format('input' if flag else 'output')

    def get_route_text(self, item: tuple[bool, str, str], input_schema: bool = False) -> str:
        tint = self.colors['route']
        text = ' '.join((
            '\033[1;{}m{}\033[0m'.format(tint, item[1]),
            '\033[0;{}m{}\033[0m'.format(tint, item[2])))
        if input_schema:
            text = ' '.join((self.get_input_schema_text(item[0]), text))
        return text

    def get_term_text(self, item: tuple[str, ...], input_schema: bool | None = None) -> str:
        template = '.'.join(map(
            lambda name: ''.join(('\033[1;{}m'.format(self.colors[name]), '{}', '\033[0m')),
            ('module', 'schema', 'field')[:len(item)]))
        text = template.format(*item)
        if input_schema is not None:
            text = ' '.join((self.get_input_schema_text(input_schema), text))
        return text

    def get_replace_text(self, text: str, size: int, orig: int, auto: bool = False) -> str:
        template = '\033[1;32m{}\033[0m'
        content = [
            template.format('Replaced by'),
            text,
            template.format(' '.join(filter(bool, ('automatically' if auto else '', 'for {} mappings'.format(size)))))]

        left = orig - size
        if left:
            content.append('\033[1;90m({})\033[0m'.format(f'{left} left unresolved'))
        return ' '.join(content)

    def get_delete_text(self, text: str, size: int) -> str:
        return '\033[0;32m{}\033[0m'.format('{} {} mappings remains marked for deletion'.format(size, text))

    def get_highlight_text(self, text: str) -> str:
        return '\033[1;97m{}\033[0m'.format(text)

    def get_option_text(self, item: str | tuple[str, ...]) -> str:
        if isinstance(item, tuple):
            if len(item) > 1:
                return '{} \033[0;90m({})\033[0m'.format(*item)
            return item[0]
        return item

    async def prompt(
        self,
        *options: str | tuple[str, str],
        default: int = 1,
        reason: bool = True,
        question: bool | str = True,
        warnings: list[str] | None = None,
        back: bool = False) -> int:

        if reason:
            text = 'Marked for deletion but it may contain references on other environments'
            print('\033[0;91m{}\033[0m. '.format(text), end='')
        else:
            print()

        if question:
            print(question if isinstance(question, str) else 'What needs to be done?')
        if warnings:
            print('\n\n'.join(warnings))
            if len(warnings) == 1:
                print()

        if back:
            print('0. Back')
        print('\n'.join(map(
            lambda item: '. '.join(map(str, item)),
            enumerate(map(self.get_option_text, options), start=1))))

        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGINT, lambda: print() or os._exit(1))

        while True:
            print(f'Select an option: [{default}]: ', end='')
            try:
                answer = int(await loop.run_in_executor(None, input) or default)
                if answer < int(not back) or answer > len(options):
                    raise ValueError
                else:
                    break
            except ValueError:
                print('\033[0;31m{}\033[0m'.format('Incorrect option!'))

        loop.remove_signal_handler(signal.SIGINT)
        return answer

    async def prompt_with_showcase(
        self,
        *options: str | tuple[str, str],
        target: str,
        reason: bool = False,
        values: list[tuple[Any, str]] | None = None,
        marked: set[tuple[Any, ...]] | None = None,
        warnings: list[str] | None = None
        ) -> int:

        answer = None
        extras = bool(values)
        while True:
            extra_options = [f'Show related {target}'] if extras else []
            answer = await self.prompt(
                *itertools.chain(options, extra_options),
                reason=extras and reason,
                warnings=warnings)
            if extras and answer == (len(options) + len(extra_options)):
                extras = False
                print('\n'.join(map(
                    lambda item: '{}{}'.format(
                        '' if not marked else self.get_highlight_text('[{}] ').format(
                            '✔' if item[0] in marked else ' '),
                        item[1]),
                    values or [])))
                continue
            else:
                return answer
