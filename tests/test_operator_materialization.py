"""Keep full CSV populations without constructing discarded row projections."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ascend_msprof_skill import operator_evidence as module


class OperatorMaterializationTests(unittest.TestCase):
    def test_only_retained_core_cells_construct_same_record_models(self):
        # A profiler CSV has many cores. Equal maxima must retain their original
        # order, and the last row must still contribute to population statistics.
        header = 'block_id,sub_block_id,aiv_time(us),aiv_vec_time(us),aiv_vec_ratio\n'
        rows = [f'{i},vector0,10,5,0.5\n' for i in range(64)]
        rows.append('64,vector0,2,1,0.1\n')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'PipeUtilization.csv'
            path.write_text(header + ''.join(rows))
            with patch.object(module, 'SameRecordCell', wraps=module.SameRecordCell) as cells:
                result = module.normalize_operator(path, path.name, 'pipe_utilization', 'op', 'Default')
            self.assertLessEqual(cells.call_count, 10)
        self.assertEqual(result.row_count, 65)
        self.assertEqual(len(result.observations), 3)
        for observation in result.observations:
            self.assertEqual(observation.source.record, 2)
            self.assertEqual(len(observation.same_record), 2)
        for distribution in result.core_time_distributions:
            self.assertEqual(distribution.valid_count, 65)
            self.assertEqual(distribution.maximum.source.record, 2)
            self.assertEqual(distribution.second_largest.source.record, 3)
        self.assertEqual(result.observations[0].derived_pipe_quotients[0].value, 0.5)


if __name__ == '__main__':
    unittest.main()
