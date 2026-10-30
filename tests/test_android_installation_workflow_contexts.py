"""Regression for real GitHub loader rejection, beyond generic YAML parsing.

GitHub's context table excludes runner from jobs.<id>.env and permits it in
steps.env/steps.with: https://docs.github.com/en/actions/reference/workflows-and-actions/contexts
This narrow guard covers our fixed workflow layout, not the entire Actions schema.
"""
import os
import contextlib
import io
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
WORKFLOWS=('.github/workflows/android-installation-x64-provider.yml',
    '.github/workflows/android-server-installation-x64.yml')


def invalid_job_runner_contexts(text):
    active=False;violations=[]
    for number,line in enumerate(text.splitlines(),1):
        if line=='    env:':active=True;continue
        if active and line.strip() and len(line)-len(line.lstrip())<=4:active=False
        if active:
            for expression in re.findall(r'\$\{\{(.*?)\}\}',line):
                if re.search(r'\brunner\s*(?:\.|\[)',expression):violations.append(number)
    return violations


def path_steps(text):
    lines=text.splitlines();result=[]
    for index,line in enumerate(lines):
        if line.strip()!='run: |':continue
        body=[]
        for following in lines[index+1:]:
            if following.strip() and len(following)-len(following.lstrip())<=8:break
            body.append(following[10:])
        script='\n'.join(body)
        if 'printf ' in script and '"$RUNNER_TEMP"' in script and '"$GITHUB_ENV"' in script:result.append(script)
    return result


class InstallationWorkflowContexts(unittest.TestCase):
    def test_actual_workflows_do_not_use_runner_context_before_a_runner_is_assigned(self):
        for name in WORKFLOWS:
            with self.subTest(workflow=name):self.assertEqual(invalid_job_runner_contexts((ROOT/name).read_text()),[])

    def test_old_job_level_context_reproduces_guard_but_step_context_remains_allowed(self):
        old='jobs:\n  measure:\n    env:\n      ROOT: ${{ runner.temp }}/fixture\n    steps:\n      - run: echo ok\n'
        self.assertEqual(invalid_job_runner_contexts(old),[4])
        self.assertEqual(invalid_job_runner_contexts(old.replace('runner.temp',"runner['temp']")),[4])
        allowed='jobs:\n  measure:\n    steps:\n      - uses: fixture/action\n        with:\n          path: ${{ runner.temp }}/fixture\n        env:\n          ROOT: ${{ runner.temp }}/fixture\n'
        self.assertEqual(invalid_job_runner_contexts(allowed),[])

    def test_actual_shell_steps_write_exact_private_paths_for_following_steps(self):
        expected={'MEASUREMENT_ROOT':'esteria-installation-provider-measurement',
            'FROZEN_MYSQL_SOURCE':'esteria-installation-frozen-mysql-817cbc',
            'INSTALLATION_SELECTION_OUT':'esteria-installation-selection',
            'INSTALLATION_OUT':'esteria-installation-x64'}
        with tempfile.TemporaryDirectory(prefix='workflow temp ') as temporary:
            temporary=Path(temporary);environment_file=temporary/'environment';environment_file.touch()
            scripts=[script for name in WORKFLOWS for script in path_steps((ROOT/name).read_text())]
            self.assertEqual(len(scripts),3)
            for script in scripts:
                subprocess.run(['bash','-e','-u','-c',script],env=dict(os.environ,RUNNER_TEMP=str(temporary),GITHUB_ENV=str(environment_file)),check=True)
            values=dict(line.split('=',1) for line in environment_file.read_text().splitlines())
            self.assertEqual(values,{name:str(temporary/suffix) for name,suffix in expected.items()})

    def test_actual_measurement_selection_runs_only_for_unmeasured_provider_state(self):
        from tools import android_installation_x64_inputs as gate
        lines=(ROOT/WORKFLOWS[0]).read_text().splitlines();bodies=[];body=None
        for line in lines:
            if "<<'PY'" in line:body=[]
            elif body is not None and line.strip()=='PY':bodies.append('\n'.join(body));body=None
            elif body is not None:body.append(line[10:])
        selection=next(source for source in bodies if "print('nativeReady='" in source)
        for state,ready in ((gate.PENDING,False),(gate.PROVIDER_PENDING,True),(gate.MEASURED,False)):
            with self.subTest(state=state),patch.object(gate,'load_pin',return_value={'state':state}) as admitted:
                output=io.StringIO()
                with contextlib.redirect_stdout(output):exec(compile(selection,'measurement-workflow-selection','exec'),{})
                self.assertEqual(output.getvalue(),'nativeReady='+str(ready).lower()+'\n')
                self.assertEqual(admitted.call_count,2 if ready else 1)
                if ready:admitted.assert_called_with(require_native=True)


if __name__=='__main__':unittest.main()
