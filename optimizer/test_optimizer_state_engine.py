from pathlib import Path
import unittest
from optimizer_state_engine import ActionRequest,OptimizerState,OptimizerTransitionEngine,TransitionError

ROOT=Path(__file__).parent
class Tests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.e=OptimizerTransitionEngine.from_csv(ROOT/'survivor_io_refund_policy_definitions.csv',ROOT/'survivor_io_optimizer_transition_rules.csv')
 def test_equipment_level(self):
  r=self.e.apply(OptimizerState(),ActionRequest('equipment_level_down','Equipment','Kunai',tracked_investment={'Gold':1000,'Equipment Designs':25}))
  self.assertEqual(r.inventory['Gold'],1000)
 def test_selector_one_way(self):
  r=self.e.apply(OptimizerState(inventory={'Selector':1}),ActionRequest('open_selector','Choice Item','S',costs={'Selector':1},fixed_returns={'Lightchaser':1}))
  self.assertTrue(r.irreversible_markers)
 def test_xeno_90(self):
  r=self.e.apply(OptimizerState(),ActionRequest('xeno_pet_dismiss','Xeno Pet','Capy',tracked_investment={'Pet Cookies':100000}))
  self.assertEqual(r.inventory['Pet Cookies'],90000)
  self.assertEqual(r.history[-1]['losses']['Pet Cookies'],10000)
 def test_unknown_block(self):
  with self.assertRaises(TransitionError):
   self.e.apply(OptimizerState(inventory={'X':1}),ActionRequest('unknown_action','Unknown','X',costs={'X':1}))
 def test_unverified_no_credit(self):
  p=self.e.preview(OptimizerState(),ActionRequest('normal_pet_unawaken','Normal Pet','Murica',tracked_investment={'Awakening Crystal':70}))
  self.assertTrue(p.legal)
  self.assertEqual(p.returns,{})
if __name__=='__main__':
 unittest.main()
