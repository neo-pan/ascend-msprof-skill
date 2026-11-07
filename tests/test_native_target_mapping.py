import unittest

from ascend_msprof_skill._profile_target import TargetSelection, match_expected_name, validate_target_subset
from ascend_msprof_skill.coverage_types import _coverage_counts, _attach_segment_target_metadata, SegmentCoverage


class NativeTargetMappingTests(unittest.TestCase):
    def target(self, name='ka_gemm_cube_0_mix_aic', application_name='ka_gemm_cube'):
        return TargetSelection.model_validate({'kernel_selector': 'ka*', 'expected_launches': [
            {'name': name, 'application_name': application_name, 'count': 1}]})

    def coverage(self, target, names):
        result = _coverage_counts([{'name': name, 'count': 1, 'duration_us': 2,
                                  'artifact': 'reports/app/PROF_1/op_summary.csv'} for name in names],
            target, application=True, authority='test rows', authority_complete=True,
            artifacts=['reports/app/PROF_1/op_summary.csv'], ambiguities=[])
        _attach_segment_target_metadata(result, target, target)
        return SegmentCoverage.model_validate(result)

    def test_native_app_mapping_preserves_names_and_counts(self):
        for op, app in [('ka_gemm_cube_0_mix_aic', 'ka_gemm_cube'), ('ka_softmax_257_0', 'ka_softmax_257')]:
            target = self.target(op, app)
            result = self.coverage(target, [app])
            self.assertTrue(result.count_complete)
            self.assertEqual(result.observed_names[0].name, app)
            self.assertEqual(match_expected_name(target, op)[1], 'exact')
            self.assertIsNone(match_expected_name(target, app)[0])
            for names in ([], [app, app], [app + '_other'], [op]):
                self.assertFalse(self.coverage(target, names).count_complete)

    def test_tilelang_suffix_path_unchanged(self):
        target = TargetSelection.model_validate({'kernel_selector': 'main*',
            'expected_launches': [{'name': 'main_kernel', 'count': 1}]})
        self.assertTrue(self.coverage(target, ['main_kernel_mix_aic']).count_complete)
        self.assertIsNone(match_expected_name(target, 'main_kernel_0')[0])

    def test_mapping_is_unique_and_followup_cannot_rewrite_it(self):
        target = self.target()
        with self.assertRaises(ValueError):
            validate_target_subset(target, self.target(application_name='wrong'))
        with self.assertRaises(ValueError):
            TargetSelection.model_validate({'kernel_selector': 'ka*', 'expected_launches': [
                {'name': 'ka_a_0', 'application_name': 'ka_a', 'count': 1},
                {'name': 'ka_b_0', 'application_name': 'ka_a', 'count': 1}]})
