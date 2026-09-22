from __future__ import annotations
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from ascend_msprof_skill.joint_row import select_records


class FieldSelectionTests(unittest.TestCase):
    def test_counts_zero_missing_invalid_and_scope_are_not_page_statistics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'PipeUtilization.csv'
            path.write_text('block_id,sub_block_id,aiv_vec_ratio,aiv_time(us),Mystery\n'
                '0,vector0,0,1,5\n1,vector0,NA,2,6\n2,vector0,bad,3,7\n3,vector0,0.8,4,8\n'
                '0,cube0,0.5,NA,9\n')
            fields=['aiv_vec_ratio','aiv_time(us)','absent','Mystery']
            result=select_records(root,path.name,'pipe_utilization',fields,limit=1)
            self.assertEqual(result['matched_records'],5)
            self.assertEqual(result['group_count'],2)
            self.assertEqual(result['returned_group_count'],1)
            self.assertEqual(result['returned_records'],1)
            self.assertFalse(result['complete'])
            stats=result['groups'][0]['fields']['aiv_vec_ratio']
            self.assertEqual((stats['valid'],stats['missing'],stats['invalid']),(2,1,1))
            self.assertEqual(result['records'][0]['fields']['aiv_vec_ratio']['value'],0)
            self.assertEqual(result['records'][0]['fields']['absent']['state'],'missing')
            self.assertEqual(result['records'][0]['fields']['Mystery']['state'],'unrecognized')
            self.assertEqual(result['groups'][0]['field_populations'][0]['valid_count'],2)
            self.assertTrue(any(issue['code']=='invalid_number' for issue in result['issues']))
            last=select_records(root,path.name,'pipe_utilization',fields,offset=4,limit=1)
            self.assertIsNone(last['next_command'])
            self.assertEqual(last['groups'][0]['scope'],{'sub_block_id':'cube0'})
            narrow=select_records(root,path.name,'pipe_utilization',fields,scope={'block_id':'0'})
            self.assertTrue(all(group['distribution_scope']=='raw_records_only' for group in narrow['groups']))

    def test_summary_uses_all_duration_cells_and_preserves_scope_and_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); path = root / 'PipeUtilization.csv'
            path.write_text('block_id,sub_block_id,aiv_time(us)\n'
                            '0,vector0,1\n1,vector0,9\n2,vector0,NA\n'
                            '3,vector0,bad\n0,vector1,0\n1,vector1,20\n')
            result = select_records(root, path.name, 'pipe_utilization', ['aiv_time(us)'],
                                    limit=1, summary_only=True)
            self.assertEqual(result['matched_records'], 6)
            self.assertEqual(len(result['groups']), 2)
            stats = result['groups'][0]['fields']['aiv_time(us)']
            self.assertEqual((stats['minimum'], stats['median'], stats['maximum']), (1, 5, 9))
            self.assertEqual((stats['valid'], stats['missing'], stats['invalid']), (2, 1, 1))
            self.assertTrue(result['summary_complete'])
            self.assertNotIn('records', result)
            selected = select_records(root, path.name, 'pipe_utilization', ['aiv_time(us)'],
                                      scope={'block_id': '0'}, summary_only=True)
            self.assertEqual(selected['matched_records'], 2)
            self.assertEqual(selected['groups'][1]['fields']['aiv_time(us)']['median'], 0)

    def test_column_order_and_scope_filters(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'PipeUtilization.csv'
            path.write_text('aiv_time(us),sub_block_id,block_id\n2,vector0,0\n3,vector1,0\n')
            result=select_records(root,path.name,'pipe_utilization',['aiv_time(us)'],scope={'sub_block_id':'vector1'})
            self.assertEqual(result['matched_records'],1)
            self.assertEqual(result['records'][0]['fields']['aiv_time(us)']['value'],3)
            self.assertEqual(result['records'][0]['fields']['aiv_time(us)']['column'],1)

    def test_real_wide_csv_cli_output_is_bounded_and_keeps_requested_fields(self):
        root=Path(__file__).resolve().parent/'fixtures/real_cann_minimal'
        candidates=list(root.rglob('PipeUtilization.csv'))
        self.assertTrue(candidates)
        path=candidates[0]
        result=subprocess.run([sys.executable,'-m','ascend_msprof_skill.joint_row','--run-dir',str(root),
            '--artifact',str(path.relative_to(root)),'--records','--field','aiv_time(us)',
            '--field','aiv_vec_ratio','--limit','2'],capture_output=True,text=True,check=True)
        # The actual shell payload fits below the normal native tool output allowance.
        self.assertLess(len(result.stdout.encode()),8000)
        payload=json.loads(result.stdout)
        self.assertEqual([f['name'] for f in payload['fields']],['aiv_time(us)','aiv_vec_ratio'])
        self.assertEqual(payload['matched_records'],payload['artifact_records'])
        self.assertIn('aiv_time(us)',payload['records'][0]['fields'])
