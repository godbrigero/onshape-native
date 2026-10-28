"""Snapshot-based FeatureScript editing without full-source copy/paste."""
import asyncio
import difflib
import os
from pathlib import Path
import tempfile

from .client import OnshapeError

MAX_BYTES = 1024 * 1024


def edited_source(original, patches=None, source=None, source_path=None):
    if sum(x is not None for x in (patches, source, source_path)) != 1:
        raise OnshapeError('Provide exactly one of patches, source, or source_path.')
    if source_path is not None:
        path = Path(source_path).expanduser()
        if not path.is_absolute() or path.suffix != '.fs' or not path.is_file():
            raise OnshapeError('source_path must be an absolute path to a UTF-8 .fs file.')
        with path.open('rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise OnshapeError('FeatureScript source exceeds 1 MiB.')
        try:
            source = raw.decode('utf-8')
        except UnicodeDecodeError:
            raise OnshapeError('FeatureScript files must be UTF-8.') from None
    if patches is not None:
        if not isinstance(patches, list) or not 1 <= len(patches) <= 100:
            raise OnshapeError('Provide 1–100 exact-text patches.')
        source = original
        for patch in patches:
            if (not isinstance(patch, dict) or set(patch) != {'old', 'new'}
                    or not isinstance(patch['old'], str) or not patch['old']
                    or not isinstance(patch['new'], str)):
                raise OnshapeError('Each patch requires nonempty old text and new text (which may be empty).')
            count = source.count(patch['old'])
            if count != 1:
                raise OnshapeError(f'Patch matches {count} locations; include enough context to match exactly once.')
            source = source.replace(patch['old'], patch['new'], 1)
    if not isinstance(source, str) or not source.strip() or len(source.encode('utf-8')) > MAX_BYTES:
        raise OnshapeError('Provide nonempty FeatureScript source of at most 1 MiB.')
    return source


class FeatureStudio:
    def __init__(self, service):
        self.s = service

    async def contents(self, target):
        raw = await self.s.call('getFeatureStudioContents', target)
        if not isinstance(raw.get('contents'), str) or not raw.get('sourceMicroversion'):
            raise OnshapeError('Feature Studio did not return source and a document revision.')
        return raw

    def snapshot(self, url, target, raw, working_copy=False):
        saved = self.s.store.put({'kind': 'feature-studio', 'url': url, 'target': target, 'raw': raw})
        result = {'snapshot': saved['artifact'], 'microversion': raw['sourceMicroversion'],
                  'line_count': len(raw['contents'].splitlines()), 'source_pointer': '/raw/contents'}
        if working_copy:
            fd, filename = tempfile.mkstemp(prefix='feature-studio-', suffix='.fs', dir=self.s.store.root)
            with os.fdopen(fd, 'w', encoding='utf-8', newline='') as stream:
                stream.write(raw['contents'])
            result['source_path'] = str(Path(filename).resolve())
        return result

    async def check(self, target, raw):
        pinned = {**target, 'wvm': 'm', 'wvmid': raw['sourceMicroversion']}
        try:
            specs = await self.s.call('getFeatureStudioSpecs', pinned)
        except OnshapeError as error:
            return {'status': 'check_failed', 'error': str(error), 'compilation_verified': False}
        return {'status': 'specs_returned', 'compilation_verified': False,
                'features': [{'name': f.get('featureTypeName'), 'type': f.get('featureType'),
                              'namespace': f.get('namespace')} for f in specs.get('featureSpecs', [])],
                'details': self.s.store.response(specs),
                'note': 'Exported feature specifications are checked at the saved revision. This endpoint does not expose complete compiler diagnostics or prove downstream geometry regenerated.'}

    async def run(self, url, action='read', snapshot='', patches=None, source=None, source_path=None, preview=False):
        target, configuration = self.s.target(url)
        if configuration:
            raise OnshapeError('Feature Studios do not accept configured URLs.')
        if action not in {'read', 'edit', 'check'}:
            raise OnshapeError('Use read, edit, or check.')
        if action != 'edit':
            if any(x is not None for x in (patches, source, source_path)) or preview:
                raise OnshapeError('Source changes and preview are only accepted for edit.')
            raw = await self.contents(target)
            result = self.snapshot(url, target, raw, working_copy=action == 'read')
            if action == 'read':
                result['source'] = raw['contents'][:12000]
                result['source_truncated'] = len(raw['contents']) > 12000
            else:
                result['check'] = await self.check(target, raw)
            return result
        if target['wvm'] != 'w':
            raise OnshapeError('FeatureScript edits require a workspace URL; versions are read-only.')
        saved = self.s.store.read(snapshot)
        if saved.get('kind') != 'feature-studio' or saved.get('target') != target:
            raise OnshapeError('Use a Feature Studio snapshot for this exact target.')
        original = saved['raw']['contents']
        updated = edited_source(original, patches, source, source_path)
        diff = ''.join(difflib.unified_diff(original.splitlines(keepends=True), updated.splitlines(keepends=True),
                                         fromfile='before.fs', tofile='after.fs'))
        difference = self.s.store.put(diff.encode('utf-8'), 'diff')
        key = 'feature-studio:' + ':'.join(target.values())
        async with self.s.locks.setdefault(key, asyncio.Lock()):
            current = await self.contents(target)
            if current['contents'] != original:
                raise OnshapeError('FeatureScript changed since the snapshot. Read it again and reapply edits; nothing was written.')
            if preview or updated == original:
                return {'preview': preview, 'changed': updated != original, 'written': False, 'diff': difference,
                        'snapshot': snapshot, 'diff_preview': diff[:12000]}
            # Refresh document revision after unrelated tab edits, while retaining an
            # exact-source comparison. The server rejects races after this preflight.
            body = {k: current[k] for k in ('serializationVersion', 'libraryVersion', 'sourceMicroversion') if k in current}
            body.update(contents=updated, rejectMicroversionSkew=True)
            await self.s.call('updateFeatureStudioContents', target, body=body)
            try:
                after = await self.contents(target)
            except OnshapeError as error:
                return {'written': True, 'verified': False, 'diff': difference, 'error': str(error),
                        'next': 'Write acknowledged; read the Feature Studio before retrying. No automatic replay.'}
            result = {**self.snapshot(url, target, after), 'written': True, 'verified': after['contents'] == updated,
                      'diff': difference, 'check': await self.check(target, after)}
            return result
