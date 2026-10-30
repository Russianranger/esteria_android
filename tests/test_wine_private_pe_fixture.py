import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('private_pe_check',ROOT/'runtime/wine-probe/private_pe_check.py')
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)


@unittest.skipUnless(hasattr(os,'waitid') and hasattr(os,'fork'),'Linux owned-process fixture')
class PrivatePeCapture(unittest.TestCase):
    def test_wine_style_detached_service_pipe_drains_only_after_explicit_shutdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);stop=root/'stop';capture=[]
            script='''import os,time,sys
read,write=os.pipe()
if os.fork()==0:
 os.close(read);os.setsid();os.write(write,b'1');os.close(write)
 deadline=time.monotonic()+4
 while not os.path.exists(sys.argv[1]) and time.monotonic()<deadline:time.sleep(.01)
 print('service-stopped',flush=True);os._exit(0)
os.close(write)
assert os.read(read,1)==b'1'
os.close(read);os._exit(0)
'''
            command=fixture.run([sys.executable,'-c',script,str(stop)],dict(os.environ),root,root/'log',2,capture)
            self.assertEqual(command.exit_code,0)
            self.assertTrue(command.reader.is_alive(),'Persistent Wine-like stdout must still be retained')
            stop.touch();receipt=command.finish(5)
            self.assertEqual(receipt['exitCode'],0);self.assertEqual((root/'log').read_bytes(),b'service-stopped\n')
            self.assertFalse(command.reader.is_alive())

    def test_output_is_drained_but_retained_bytes_are_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);captures=[]
            command=fixture.run([sys.executable,'-c','import sys;sys.stdout.buffer.write(b"x"*(3*1024*1024))'],
                dict(os.environ),root,root/'log',5,captures)
            with self.assertRaises(ValueError):command.finish(5)
            self.assertEqual(len(command.kept),fixture.MAX_LOG);self.assertGreater(command.count,fixture.MAX_LOG)
            self.assertEqual((root/'log').stat().st_size,fixture.MAX_LOG);self.assertFalse(command.reader.is_alive())

    def test_timeout_reaps_owned_leader_and_keeps_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);captures=[]
            with self.assertRaises(ValueError):fixture.run([sys.executable,'-c','import time;time.sleep(30)'],
                dict(os.environ),root,root/'log',.01,captures)
            self.assertEqual(len(captures),1);command=captures[0]
            self.assertTrue(command.timed_out);self.assertTrue(command.owner.closed)
            command.finish(5);self.assertFalse(command.reader.is_alive())


if __name__=='__main__':unittest.main()
