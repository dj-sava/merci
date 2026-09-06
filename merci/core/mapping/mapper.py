import functools
import itertools
import os
import zlib
from typing import Any, Generic, TypeVar, cast

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from ..console import Shell
from .mixins import IdentifierMapping, IdentifierMappingMigration

IdentifierMappingType = TypeVar('IdentifierMappingType', bound=IdentifierMapping)
IdentifierMappingMigrationType = TypeVar('IdentifierMappingMigrationType', bound=IdentifierMappingMigration)


class IdentifierMapper(Generic[IdentifierMappingType, IdentifierMappingMigrationType]):
    def __init__(
        self,
        session: AsyncSession,
        mapping_model: type[IdentifierMappingType],
        mapping_migration_model: type[IdentifierMappingMigrationType]):

        self.shell = Shell()
        self.session = session
        self.mapping_model = mapping_model
        self.mapping_migration_model = mapping_migration_model

    async def acquire(self) -> bool:
        bind = self.session.get_bind()
        if bind.dialect.name != 'postgresql':
            raise NotImplementedError
        elif not await self.session.scalar(
            text('SELECT pg_try_advisory_lock(:id)'),
            {'id': zlib.crc32(b'identifier_mapper_lock')}):
            return False
        else:
            return True

    async def resolve(
        self,
        entry: str,
        path: tuple[str, ...],
        suit: dict[tuple[Any, ...], Any],
        bank: dict[tuple[Any, ...], Any],
        fill: dict[int, int],
        skip: dict[str, set[int]] | None = None,
        relations: list[tuple[Any, str]] | None = None,
        help_text: str | None = None
        ) -> list[IdentifierMappingMigrationType]:

        get_item_text = getattr(self.shell, 'get_{}_text'.format(entry if entry == 'route' else 'term'))

        line = ' '.join((self.shell.get_entry_text(entry), 'entry', get_item_text(path)))
        if entry == 'route' and path[0]:
            line = ' '.join((self.shell.get_highlight_text('input'), line))
        line = self.shell.capitalize(line)

        show = 'mappings'
        if entry == 'route':
            show = 'fields'
        elif entry == 'field':
            show = 'routes'
        print(line)

        result = []
        scores = {}

        orig_items = set(suit.keys())
        orig_count = len(orig_items)

        for swap_path, swap_suit in bank.items():
            if entry == 'route' and path[0] != swap_path[0]:
                continue
            scores[swap_path] = set(swap_suit.keys()) & orig_items

        actions: list[str | tuple[str, str]] = ['Replace', 'Delete']
        if help_text:
            actions[0] = (cast(str, actions[0]), help_text)
        options = sorted(filter(scores.get, bank.keys()), key=lambda item: len(scores[item]), reverse=True)

        if len(options) == 1:
            choices = {options[0]}
        else:
            choices = {k for k, v in scores.items() if len(v) == orig_count}

        if len(choices) == 1:
            swap_path = choices.pop()
            swap_suit = bank[swap_path]
            options.remove(swap_path)

            print(self.shell.get_replace_text(
                get_item_text(swap_path),
                size=len(scores[swap_path]),
                orig=orig_count,
                auto=True))

            answer = await self.shell.prompt_with_showcase(
                'Confirm',
                ('Decline', 'continue processing manually'),
                target=show,
                values=relations,
                marked=scores[swap_path])

            if answer == 2:
                print()
                print(line)
            else:
                if answer == 1:
                    for item in orig_items:
                        if item in swap_suit:
                            old_index_data, reference_id = suit[item]
                            new_index_data = swap_suit[item][0]
                            if skip:
                                skip['remove'].add(old_index_data)
                                skip['append'].add(new_index_data)

                            if reference_id:
                                fill[new_index_data] = reference_id
                            obj = self.mapping_migration_model( # type: ignore[call-arg]
                                old_index_data=old_index_data,
                                new_index_data=new_index_data,
                                applied=True)
                            result.append(obj)
                return result

        answer = 0
        while answer == 0:
            warnings = []
            if not options:
                warnings.append(self.shell.get_highlight_text(
                    'It can not be replaced because there are no matches with appending mappings!'))
                actions = [
                    ('Exit', f'{entry} mapping have multiple changes and should applied one by one'),
                    ('Delete', f'{entry} mapping does not really exists anymore')]

            answer = await self.shell.prompt_with_showcase(
                *actions,
                reason=not bool(answer),
                target=show,
                values=relations,
                warnings=warnings)

            if answer == 1:
                if not options:
                    os._exit(1)
                question = f'Which {entry} should be used?'
                answer = await self.shell.prompt(
                    *map(get_item_text, options),
                    reason=not bool(answer),
                    question=question,
                    back=True)

                if answer == 0:
                    print()
                    print(line)
                else:
                    size = 0
                    swap_path = options[answer - 1]

                    swap_suit = bank.pop(swap_path)
                    for item in orig_items:
                        old_index_data, reference_id = suit[item]
                        new_index_data = swap_suit.get(item)[0]
                        if new_index_data:
                            size += 1
                            if skip:
                                skip['remove'].add(old_index_data)
                                skip['append'].add(new_index_data)
                            if reference_id:
                                fill[new_index_data] = reference_id
                            obj = self.mapping_migration_model( # type: ignore[call-arg]
                                old_index_data=old_index_data,
                                new_index_data=new_index_data,
                                applied=True)
                            result.append(obj)

                    print()
                    print(line)
                    print(self.shell.get_replace_text(get_item_text(swap_path), size=size, orig=orig_count))
                    print()
            else:
                if skip:
                    skip['remove'] |= set(suit.values())
                print(self.shell.get_delete_text(entry, len(orig_items)))
        return result

    async def migrate(
        self,
        data: dict[int, dict[str, Any]],
        commit: bool = True
        ) -> tuple[list[IdentifierMappingType], list[IdentifierMappingMigrationType]] | None:

        if not await self.acquire():
            return None

        stored = set((await self.session.execute(select(self.mapping_model.index_data))).scalars().all())
        actual = set(data.keys())

        change: list[IdentifierMappingMigrationType] = []
        append: list[IdentifierMappingType] = []
        remove = stored - actual

        history: dict[str, dict[int, int]] = {'flow': {}, 'link': {}}
        effects = list(await self.session.scalars(
            select(self.mapping_migration_model) \
            .filter_by(applied=False) \
            .order_by(self.mapping_migration_model.id.asc())))

        if effects and not effects[0].migration_id:
            list.reverse(effects)

        for effect in effects:
            if effect.old_index_data in history['flow']:
                history['flow'][effect.new_index_data] = history['flow'].pop(effect.old_index_data)
            else:
                history['flow'][effect.new_index_data] = effect.old_index_data

            if effect.migration_id:
                effect.applied = True
            else:
                await self.session.delete(effect)

        records = await self.session.scalars(
            select(self.mapping_model) \
            .options(load_only(self.mapping_model.index_data, self.mapping_model.reference_id))
            .filter(self.mapping_model.index_data.in_(history['flow'].values())))

        for record in records:
            if record.reference_id:
                history['link'][record.index_data] = record.reference_id

        if remove:
            stmt = (
                delete(self.mapping_model)
                .filter(self.mapping_model.index_data.in_(remove))
                .returning(self.mapping_model))
            rows = tuple(map(lambda item: item[0], await self.session.execute(stmt)))

        append = list(map(
            lambda index: self.mapping_model( # type: ignore[call-arg]
                index_data=index,
                reference_id=None if index not in history['flow'] else history['link'].get(history['flow'][index]),
                **data[index]),
            actual - stored))

        if not remove or len(append) == len(history['flow']):
            await self.release(append, change, commit)
            return (append, change)

        fill: dict[int, int] = {}
        skip: dict[str, set[int]] = {'remove': set(), 'append': set()}
        pool: dict[str, Any] = {'remove': rows, 'append': append}

        path_keys = ('input_schema', 'route_method', 'route_path')
        term_keys = ('module_name', 'schema_name', 'field_name')

        diff: dict[str, Any] = {}
        tree: dict[str, Any] = {}
        swap: list[dict[str, str]] = []

        def distribute(data: dict[str, Any], from_term: bool = False, skip: dict[str, set[int]] | None = None) -> None:
            for kind in data.keys():
                diff[kind] = {}
                tree[kind] = {}

            for kind, pack in data.items():
                for item in pack:
                    if skip and item.index_data in skip[kind]:
                        continue

                    if from_term:
                        root = tree[kind]
                        for attr in term_keys:
                            seed = getattr(item, attr)
                            if seed not in root:
                                root[seed] = {}
                            root = root[seed]

                    func = functools.partial(getattr, item)
                    head, tail = map(
                        lambda keys: tuple(map(func, keys)),
                        (term_keys, path_keys) if from_term else (path_keys, term_keys))

                    if head not in diff[kind]:
                        diff[kind][head] = {}
                    diff[kind][head][tail] = (item.index_data, item.reference_id)

        def overspread(
            kind: str,
            path: tuple[str, ...] | None = None,
            root: dict[str, Any] | None = None,
            head: list[str] | None = None,
            deep: int = 1,
            stop: int = 0,
            ) -> Any: # TODO: redesign function to cast to simple types

            result = []
            if root is None:
                root = tree[kind]
                if path:
                    for seed in path:
                        root = root[seed]

            if head is None:
                head = []

            for leaf, fork in root.items():
                body = head + [leaf]
                if fork and not (stop and deep == stop):
                    result.extend(overspread(kind, path, fork, body, deep + 1, stop))
                else:
                    if deep == stop:
                        result.append(tuple(body))
                    elif path:
                        for tail, form in diff[kind][tuple(itertools.chain(path, body))].items():
                            result.append((tuple(itertools.chain(body, tail)), form))
            return result

        async def exists_other_records(spec: dict[str, str]) -> bool:
            stmt = select(self.mapping_model.id).filter_by(**spec).limit(1)
            return await self.session.scalar(stmt) is not None

        async def exists_other_entries(root: dict[str, Any], spec: dict[str, str]) -> bool:
            flag = True
            for attr in term_keys[:-1]:
                if attr in spec:
                    if spec[attr] in root:
                        root = root[spec[attr]]
                    else:
                        flag = False
                        break

            if not flag:
                flag = await exists_other_records(spec)
            return flag

        async def handle_graph(root: dict[str, Any], spec: dict[str, str] | None = None) -> None:
            spec = spec or {}
            deep = len(spec)

            if deep == len(term_keys):
                swap.append(spec)
                return

            keys = tuple(root.keys())
            if len(keys) > 1:
                # check top-level entries existance
                if deep and not await exists_other_entries(tree['append'], spec):
                    swap.append(spec)
                    return

            for item in keys:
                await handle_graph(root[item], spec | dict([(term_keys[deep], item)]))

        # check routes changings
        skip['append'] |= set(history['flow'].keys())
        skip['remove'] |= set(history['flow'].values())
        distribute(pool)

        for path, suit in diff['remove'].items():
            showcase = sorted(map(lambda item: (item, self.shell.get_term_text(item, path[0])), suit.keys()))

            if len(suit) == 1:
                continue

            if path in diff['append'] or await exists_other_records(dict(zip(path_keys, path))):
                # terms changes will be processed later
                continue

            change.extend(await self.resolve(
                entry='route',
                path=path,
                suit=suit,
                bank=diff['append'],
                skip=skip,
                fill=fill,
                relations=showcase,
                help_text='choose if route address or route method were changed'))

        # check terms changings
        distribute(pool, from_term=True, skip=skip)
        await handle_graph(tree['remove'])

        size = len(term_keys)
        skip = {attr: set() for attr in term_keys}
        bank: dict[int, dict[tuple[str, ...], dict[str, tuple[int, ...]]]] = {}

        for deep in range(1, size):
            bank[deep] = {}
            for path in overspread('append', stop=deep):
                # path = cast(tuple[str, ...], path)
                bank[deep][path] = {}

                for pair in overspread('append', path):
                    # assert len(pair) == 2
                    term, form = pair
                    bank[deep][path][term] = form

        for spec in sorted(swap, key=len):
            deep = len(spec)
            name = term_keys[deep - 1].split('_')[0]
            path = tuple(map(spec.get, term_keys[:deep]))
            help_text = f'choose if {name} was renamed'

            if deep < size:
                suit = {}
                for pair in overspread('remove', path):
                    # assert len(pair) == 2
                    term, form = pair
                    suit[term] = form

                showcase = sorted(map(
                    lambda item: (item[0], self.shell.get_highlight_text(' -> ').join((
                        self.shell.get_term_text(item[1][:size], item[1][size]),
                        self.shell.get_route_text(item[1][size:])))),
                    map(
                        lambda item: (item, tuple(itertools.chain(path, item))),
                        suit.keys())))
            else:
                suit = diff['remove'][path]
                showcase = sorted(map(
                    lambda item: (item, self.shell.get_route_text(item, input_schema=True)),
                    suit.keys()))

            change.extend(await self.resolve(
                entry=name,
                path=path,
                suit=suit,
                bank=bank.get(deep, diff['append']),
                fill=fill,
                skip=None,
                relations=showcase,
                help_text=help_text))

        for item in append:
            if item.index_data in fill:
                item.reference_id = fill[item.index_data]

        await self.release(append, change, commit)
        return (append, change)

    async def release(
        self,
        append: list[IdentifierMappingType],
        change: list[IdentifierMappingMigrationType],
        commit: bool) -> None:

        notice = bool(change)
        if not notice:
            stmt = (
                select(self.mapping_migration_model.id)
                .filter(self.mapping_migration_model.migration_id.is_(None))
                .limit(1)
            )
            notice = await self.session.scalar(stmt) is not None

        if notice:
            print()
            print(self.shell.get_highlight_text(
                'You need to make alembic revision to transfer mappings changes on other environments'))
            print()

        for kit in (append, change):
            for obj in kit:
                self.session.add(obj)
        if commit:
            await self.session.commit()
