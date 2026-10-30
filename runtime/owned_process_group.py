"""Retain a Linux child identity through owned process-group cleanup.

Callers must start the child with start_new_session=True and never call poll/wait
themselves. WNOWAIT reserves the leader PID even after exit; only stop() reaps it.
"""
import os
import signal
import subprocess
import time


class OwnedGroup:
    def __init__(self, process):
        if process.returncode is not None or os.getpgid(process.pid) != process.pid:
            raise ValueError('fresh owned process-group leader required')
        self.process = process
        self.closed = False
        self.forced = False
        self.status = None

    def observe(self):
        if self.closed:
            return self.status
        if self.process.returncode is not None:
            raise ValueError('process leader was reaped outside its owner; no group signal permitted')
        try:
            state = os.waitid(os.P_PID, self.process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        except ChildProcessError as error:
            raise ValueError('process leader identity no longer owned; no group signal permitted') from error
        if state is None:
            return None
        if state.si_code == os.CLD_EXITED:
            return state.si_status
        if state.si_code in (os.CLD_KILLED, os.CLD_DUMPED):
            return -state.si_status
        raise ValueError('unexpected child observation')

    def wait(self, timeout):
        deadline = time.monotonic() + timeout
        while True:
            status = self.observe()
            if status is not None:
                return status
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(self.process.args, timeout)
            time.sleep(min(.02, max(0, deadline - time.monotonic())))

    def _signal(self, number):
        self.observe()  # Fail without signalling if someone else reaped the PID.
        if self.closed:
            return
        try:
            os.killpg(self.process.pid, number)
        except ProcessLookupError:
            pass

    def stop(self, graceful_timeout=10, reap_timeout=5):
        if self.closed:
            return self.status, self.forced
        self.observe()
        try:
            if self.observe() is None:
                self._signal(signal.SIGTERM)
                try:
                    self.wait(graceful_timeout)
                except subprocess.TimeoutExpired:
                    self.forced = True
        finally:
            # The leader is still alive or waitable here. Its reserved PID cannot
            # have been reused for an unrelated process group.
            self._signal(signal.SIGKILL)
            self.status = self.process.wait(timeout=reap_timeout)
            self.closed = True
        return self.status, self.forced
