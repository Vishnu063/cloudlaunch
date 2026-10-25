import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('release',Path(__file__).resolve().parents[1]/'scripts/report-release.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class ReportingTests(unittest.TestCase):
 def test_disabled_reporting_is_private_local_and_does_not_deploy(self):
  with tempfile.TemporaryDirectory() as root,patch.object(module,'release_id',return_value='a'*40),patch.dict('os.environ',{},clear=True):
   r=module.report('healthy',root);self.assertFalse(r['delivered']);self.assertEqual(0o600,(Path(root)/'deployments.jsonl').stat().st_mode&0o777)
   self.assertIn('cloudlaunch_deployment_status{status="healthy"} 1',(Path(root)/'release.prom').read_text())
 def test_unknown_outcome_is_refused(self):
  with self.assertRaises(ValueError):module.report('pretend-success','unused')

class DeployerBoundaryTests(unittest.TestCase):
 def test_cleanup_refuses_a_foreign_container(self):
  spec=importlib.util.spec_from_file_location('deployer',Path(__file__).resolve().parents[1]/'scripts/deploy-ecosystem-demo.py')
  deployer=importlib.util.module_from_spec(spec);spec.loader.exec_module(deployer)
  with patch.object(deployer,'docker',return_value='[{"Config":{"Labels":{"io.cloudlaunch.ecosystem-demo":"foreign"}}}]') as command:
   with self.assertRaises(ValueError):deployer.cleanup({'container':'candidate','token':'owned'})
   self.assertEqual(1,command.call_count)
