from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from windbridge.server import create_app
from windbridge.state import BridgeState, safe_filename
from windbridge.uploads import CHUNK_SIZE, MAX_FILE_SIZE, RETENTION_SECONDS

ROOT = Path(__file__).resolve().parents[1]
digest = lambda data: hashlib.sha256(data).hexdigest()


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.restart()

    def restart(self):
        self.state = BridgeState(self.folder / 'incoming')
        self.app = create_app(self.state, ROOT / 'web')
        self.client = self.app.test_client()
        self.auth = {'X-WindBridge-Token': self.state.token}
        self.store = self.app.extensions['uploads']

    def init(self, size=3, name='test.bin', fingerprint=None):
        response = self.client.post('/api/uploads', json={
            'name': name, 'size': size, 'fingerprint': fingerprint or digest(name.encode())}, headers=self.auth)
        self.assertIn(response.status_code, (200, 201), response.get_json())
        return response.get_json()

    def put(self, session, data, offset=None, checksum=None):
        return self.client.put('/api/uploads/'+session['id'], data=data, headers={**self.auth,
            'Upload-Offset': str(session['offset'] if offset is None else offset),
            'X-Chunk-SHA256': checksum or digest(data)})

    def finish(self, session):
        return self.client.post('/api/uploads/'+session['id']+'/complete', headers=self.auth)

    def test_restart_resume_complete_retry_and_auth_rotation(self):
        data = b'a' * CHUNK_SIZE + b'last block'
        session = self.init(len(data))
        response = self.put(session, data[:CHUNK_SIZE])
        self.assertEqual(response.status_code, 200)
        old_auth = self.auth
        self.restart()
        self.assertEqual(self.client.get('/api/uploads', headers=old_auth).status_code, 401)
        resumed = self.init(len(data))
        self.assertEqual(resumed['id'], session['id'])
        self.assertEqual(resumed['offset'], CHUNK_SIZE)
        self.assertEqual(resumed['hashes'], [digest(data[:CHUNK_SIZE])])
        self.assertEqual(self.put(resumed, data[CHUNK_SIZE:]).status_code, 200)
        result = self.finish(session)
        self.assertEqual(result.status_code, 200, result.get_json())
        self.assertEqual(result.json['file']['sha256'], digest(data))
        self.assertEqual((self.state.incoming_dir/'test.bin').read_bytes(), data)
        self.assertEqual(self.finish(session).json, result.json)
        self.assertEqual(len(self.state.inbound), 1)

    def test_offsets_hashes_lengths_and_incomplete(self):
        session = self.init()
        self.assertEqual(self.put(session, b'abc', checksum='0'*64).status_code, 422)
        self.assertEqual(self.put(session, b'ab').status_code, 400)
        self.assertEqual(self.put(session, b'abc', offset=1).status_code, 409)
        self.assertEqual(self.finish(session).status_code, 409)
        self.assertEqual(self.put(session, b'abc').status_code, 200)
        self.assertEqual(self.put(session, b'abc').status_code, 409)
        self.assertEqual(self.put(session, b'x'*(CHUNK_SIZE+1)).status_code, 413)

    def test_zero_file_and_cancel_does_not_delete_final(self):
        session = self.init(0)
        self.assertEqual(self.finish(session).status_code, 200)
        for _ in range(2):
            self.assertEqual(self.client.delete('/api/uploads/'+session['id'], headers=self.auth).status_code, 204)
        self.assertEqual((self.state.incoming_dir/'test.bin').read_bytes(), b'')
        self.assertEqual(self.store.list_sessions(), [])

    def test_cancel_partial_and_expiry(self):
        first = self.init()
        self.client.delete('/api/uploads/'+first['id'], headers=self.auth)
        self.assertFalse((self.store.root/(first['id']+'.part')).exists())
        second = self.init()
        manifest = self.store.root/(second['id']+'.json')
        old = time.time()-RETENTION_SECONDS-1
        os.utime(manifest, (old, old))
        self.assertEqual(self.store.list_sessions(), [])
        self.assertFalse((self.store.root/(second['id']+'.part')).exists())

    def test_invalid_requests_and_auth(self):
        for payload in ([], None, {}, {'name':'a','size':True,'fingerprint':'0'*64},
                        {'name':'a','size':-1,'fingerprint':'0'*64},
                        {'name':'a','size':3,'fingerprint':'bad'}):
            self.assertEqual(self.client.post('/api/uploads', json=payload, headers=self.auth).status_code, 400)
        self.assertEqual(self.client.post('/api/uploads', json={'name':'a','size':MAX_FILE_SIZE+1,'fingerprint':'0'*64}, headers=self.auth).status_code, 413)
        session = self.init()
        for method, path in [('get',''),('post',''),('get','/'+session['id']),('put','/'+session['id']),
                             ('delete','/'+session['id']),('post','/'+session['id']+'/complete')]:
            self.assertEqual(getattr(self.client, method)('/api/uploads'+path).status_code, 401)
        self.assertEqual(self.client.get('/api/uploads/invalid', headers=self.auth).status_code, 404)
        self.assertEqual(self.client.put('/api/uploads/'+session['id'], headers=self.auth).status_code, 400)

    def test_disk_full_and_corrupt_partial(self):
        session = self.init()
        with patch('windbridge.uploads.shutil.disk_usage') as usage:
            usage.return_value.free = 0
            self.assertEqual(self.put(session, b'abc').status_code, 507)
        self.assertEqual(self.put(session, b'abc').status_code, 200)
        (self.store.root/(session['id']+'.part')).write_bytes(b'xyz')
        self.assertEqual(self.finish(session).status_code, 422)
        self.assertFalse((self.state.incoming_dir/'test.bin').exists())

    def test_uncommitted_tail_discarded_after_restart(self):
        session = self.init()
        part = self.store.root/(session['id']+'.part')
        part.write_bytes(b'uncommitted')
        self.restart()
        self.assertEqual(self.store.status(session['id'])['offset'], 0)
        self.assertEqual(part.stat().st_size, 0)

    def test_crash_after_publication_before_receipt(self):
        session = self.init()
        self.put(session, b'abc')
        save = self.store._save
        def crash(record):
            if record['status'] == 'completed':
                raise OSError('simulated crash')
            save(record)
        with patch.object(self.store, '_save', side_effect=crash):
            self.assertEqual(self.finish(session).status_code, 500)
        self.restart()
        self.assertEqual(self.finish(session).status_code, 200)
        self.assertEqual(len(list(self.state.incoming_dir.glob('test*.bin'))), 1)

    def test_same_name_parallel_completion_and_long_names(self):
        name = 'a'*176+'.bin'
        sessions = [self.init(name=name, fingerprint=digest(bytes([i]))) for i in range(2)]
        for session in sessions:
            self.put(session, b'abc')
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda s: self.store.complete(s['id']), sessions))
        names = [result['file']['name'] for result in results]
        self.assertEqual(len(set(names)), 2)
        self.assertTrue(all((self.state.incoming_dir/name).read_bytes()==b'abc' for name in names))
        self.assertEqual(safe_filename(safe_filename('CON.'+'a'*190)), safe_filename('CON.'+'a'*190))

    def test_download_range_and_if_range(self):
        path = self.folder/'download.bin'
        path.write_bytes(b'0123456789')
        item = self.state.add_outbound([path])[0]
        url = f'/api/files/{item.id}/download'
        with self.client.get(url, headers={**self.auth,'Range':'bytes=4-'}) as response:
            self.assertEqual(response.status_code, 206)
            self.assertEqual(response.data, b'456789')
            self.assertEqual(response.headers['Content-Range'], 'bytes 4-9/10')
            tag = response.headers['ETag']
        with self.client.get(url, headers={**self.auth,'Range':'bytes=99-'}) as response:
            self.assertEqual(response.status_code, 416)
        path.write_bytes(b'abcdefghij')
        with self.client.get(url, headers={**self.auth,'Range':'bytes=4-','If-Range':tag}) as response:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, b'abcdefghij')


if __name__ == '__main__':
    unittest.main()
