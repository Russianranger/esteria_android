"""Source-bound stock disk layouts; synthetic rows do not qualify gameplay."""
from contextlib import redirect_stdout
import io,json,struct,tempfile,unittest
from pathlib import Path
from runtime import server_data_preflight as f,stock_content_inspection as client

def dbc(shape):
    fields,stride=shape
    return struct.pack('<4s4I',b'WDBC',1,fields,stride,1)+bytes(stride)+b'\0'

class StockServerDiskLayouts(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name)
    def write(self,name,raw):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw);return p
    def world(self,classic=True):
        for name,shape in f.STOCK_DISK_LAYOUTS.items():self.write('dbc/'+name,dbc(shape if classic else f.DBC_LAYOUTS[name][:2]))
        self.write('dbc/gtOCTClassCombatRatingScalar.dbc',dbc((2,8)))
        self.write('maps/0000000.map',struct.pack('<4s10I',b'MAPS',9,12340,*([0]*8)))
        self.write('vmaps/000.vmtree',b'VMAP_4.8');self.write('mmaps/000.mmap',bytes(28))
        self.write('Cameras/test.m2',b'MD20'+struct.pack('<I',264))
    def test_whitelist_exactly_matches_pinned_client_server_difference(self):
        difference={}
        for virtual,shape in client.CLIENT_DBC_LAYOUTS.items():
            name=virtual.rsplit('\\',1)[-1].casefold()
            if name in f.DBC_LAYOUTS and shape!=f.DBC_LAYOUTS[name][:2]:difference[name]=shape
        self.assertEqual(len(difference),11);self.assertEqual(f.STOCK_DISK_LAYOUTS,difference)
        source=f.STOCK_DISK_LAYOUT_SOURCE
        self.assertEqual(source['clientRevision'],client.CLIENT_REVISION)
        self.assertEqual(source['clientLayoutSourceSha256'],client.CLIENT_DBC_LAYOUT_SOURCE_SHA256)
        self.assertEqual(source['serverRevision'],f.SERVER_REVISION)
        self.assertEqual(source['serverLoaderSha256'],f.DBC_LAYOUT_SOURCE['sourceFiles']['src/server/game/DataStores/DBCStores.cpp']['sha256'])
    def test_classic_shapes_stock_only_bytes_unchanged_and_custom_strict(self):
        for name,shape in f.STOCK_DISK_LAYOUTS.items():
            with self.subTest(name=name):
                p=self.write('dbc/'+name,dbc(shape));before=p.read_bytes(),p.stat().st_mtime_ns
                self.assertIsNone(f.check_dbc(p,content_profile='stock-3.3.5a'))
                self.assertEqual((p.read_bytes(),p.stat().st_mtime_ns),before)
                with self.assertRaisesRegex(ValueError,'pinned server DBC layout'):f.check_dbc(p)
    def test_scalar_other_stores_and_wrong_classic_shapes_stay_strict(self):
        for name,shape in [('gtOCTClassCombatRatingScalar.dbc',(1,4)),('Map.dbc',(1,4)),('PowerDisplay.dbc',(6,16)),('gtCombatRatings.dbc',(2,4))]:
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'pinned server DBC layout'):
                f.check_dbc(self.write('dbc/'+name,dbc(shape)),content_profile='stock-3.3.5a')
        f.check_dbc(self.write('dbc/gtOCTClassCombatRatingScalar.dbc',dbc((2,8))),content_profile='stock-3.3.5a')
    def test_magic_header_and_declared_lengths_remain_required(self):
        p=self.write('dbc/gtCombatRatings.dbc',dbc((1,4)));raw=p.read_bytes()
        for bad in (raw[:-1],raw+b'\0',b'BAD!'+raw[4:],raw[:19]):
            p.write_bytes(bad)
            with self.assertRaises(ValueError):f.check_dbc(p,content_profile='stock-3.3.5a')
    def test_report_distinguishes_ten_sql_stores_and_native_powerdisplay(self):
        self.world();before={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        report=f.check_server_data(self.root,content_profile='stock-3.3.5a')
        self.assertTrue(report['checks_passed'],report);self.assertFalse(report['gameplay_qualified'])
        c=report['stock_disk_layout_compatibility'];self.assertEqual(c['files_checked'],11)
        self.assertEqual(len(c['source_sql_tables']),10);self.assertEqual(c['native_disk_tables'],['powerdisplay.dbc'])
        self.assertFalse(c['payload_rewritten']);self.assertEqual(before,{p:p.read_bytes() for p in before})
        strict=f.check_server_data(self.root);self.assertEqual(strict['error_count'],11)
    def test_legacy_success_report_stays_identical(self):
        self.world(False);old=f.check_server_data(self.root);self.assertTrue(old['checks_passed'])
        self.assertEqual(old,f.check_server_data(self.root,content_profile='stock-3.3.5a'))
        self.assertNotIn('stock_disk_layout_compatibility',old)
    def test_other_format_failure_is_not_hidden(self):
        self.world();self.write('maps/0000000.map',struct.pack('<4s10I',b'MAPS',9,12340,44,100,*([0]*6)))
        r=f.check_server_data(self.root,content_profile='stock-3.3.5a');self.assertFalse(r['checks_passed'])
        self.assertEqual(r['error_count'],1);self.assertEqual(r['errors'][0]['path'],'maps/0000000.map')
    def test_continuations_keep_server_layout_and_base_agreement(self):
        p=self.write('dbc-continuations/gtCombatRatings.dbc1-test',dbc((1,4)))
        with self.assertRaisesRegex(ValueError,'pinned server DBC layout'):f.check_dbc(p,content_profile='stock-3.3.5a')
        p.write_bytes(dbc((2,8)));f.check_dbc(p,content_profile='stock-3.3.5a');self.world()
        r=f.check_server_data(self.root,content_profile='stock-3.3.5a');self.assertFalse(r['checks_passed'])
        self.assertTrue(any(row['path']=='dbc-continuations' for row in r['errors']))
    def test_unknown_profile_is_not_a_layout_override(self):
        p=self.write('dbc/gtCombatRatings.dbc',dbc((1,4)))
        for profile in (None,True,'','classic','stock','STOCK-3.3.5a'):
            with self.subTest(profile=profile),self.assertRaises(ValueError):f.check_dbc(p,content_profile=profile)
    def test_cli_requires_explicit_stock_selection(self):
        self.world();out=io.StringIO()
        with redirect_stdout(out):code=f.main(['--server-data',str(self.root),'--content-profile','stock-3.3.5a'])
        self.assertEqual(code,0);self.assertTrue(json.loads(out.getvalue())['checks_passed'])
        with redirect_stdout(io.StringIO()):self.assertEqual(f.main(['--server-data',str(self.root)]),2)

if __name__=='__main__':unittest.main()
