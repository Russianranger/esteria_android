import hashlib
import io
import http.client
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import time
import zipfile

from tools import qualify_stock_shader_corpus as corpus


class StockShaderCorpus(unittest.TestCase):
    def setUp(self):
        self.payload = bytes(range(251)) * 1000
        self.name = corpus.PREFIX + 'Data/enUS/locale-enUS.MPQ'
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(self.name, self.payload)
            info = archive.getinfo(self.name)
        self.archive = buf.getvalue()
        self.row = dict(path=self.name, local=info.header_offset, compressed=info.compress_size,
                        crc=info.CRC, bytes=info.file_size, method=info.compress_type)
        self.piece = 64
        self.hashes = b''.join(hashlib.sha1(self.archive[pos:pos + self.piece]).digest()
                               for pos in range(0, len(self.archive), self.piece))

    def extract(self, root, row):
        return corpus.extract(row, root, self.hashes, lambda lo, hi: self.archive[lo:hi],
                              len(self.archive), self.piece)

    def test_verified_piece_slices_header_and_complete_deflate(self):
        with TemporaryDirectory() as temp:
            path = self.extract(Path(temp), self.row)
            self.assertEqual(path.read_bytes(), self.payload)
            self.assertEqual(path.relative_to(temp).as_posix(), 'Data/enUS/locale-enUS.MPQ')
            with self.assertRaises(FileExistsError):
                self.extract(Path(temp), self.row)

    def test_resume_verified_partial_and_incomplete_http_bodies(self):
        calls = []
        class Response(io.BytesIO):
            status = 206

            def geturl(self):
                return corpus.URL

            def read(self, n=-1):
                if len(calls) == 2:
                    raise http.client.IncompleteRead(super().read(5))
                return super().read(n)

        def open_range(request, timeout):
            lo, hi = map(int, request.headers['Range'][6:].split('-'))
            calls.append(lo)
            self.assertEqual((request.headers['If-match'], hi), (corpus.ETAG, 60))
            stop = lo + 3 if len(calls) == 1 else hi + 1
            response = Response(self.archive[lo:stop])
            response.headers = {'ETag': corpus.ETAG, 'Content-Range': f'bytes {lo}-{hi}/{corpus.TOTAL}'}
            return response

        fetched = corpus.range_bytes(13, 61, time.monotonic() + 5, opener=open_range)
        self.assertEqual(calls, [13, 16, 21])
        self.assertEqual(fetched, self.archive[13:61])

    def test_piece_change_even_outside_requested_interval(self):
        corrupt = bytearray(self.archive)
        corrupt[0] ^= 1
        with self.assertRaisesRegex(corpus.Invalid, 'torrent piece'):
            list(corpus.verified_slices(4, 8, self.hashes, lambda lo, hi: corrupt[lo:hi],
                                        len(corrupt), self.piece))

    def test_crc_size_header_and_name_checks(self):
        for patch in ({'crc': 1}, {'bytes': 3}, {'local': 2}, {'path': self.name.replace('enUS/', '../')}):
            with self.subTest(patch=patch), TemporaryDirectory() as temp, self.assertRaises(corpus.Invalid):
                self.extract(Path(temp), dict(self.row, **patch))

    def test_pinned_effective_english_members(self):
        rows = json.loads(corpus.LOCK.read_bytes())
        self.assertEqual(len({r['path'] for r in rows}), 16)
        self.assertEqual(sum(r['bytes'] for r in rows), 17068352907)
        self.assertTrue(all(r['method'] == 8 and 0 <= r['local'] < corpus.TOTAL for r in rows))


if __name__ == '__main__':
    unittest.main()
