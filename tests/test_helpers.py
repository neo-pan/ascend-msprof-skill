"""Compatibility test interface for the split helper test modules."""

import unittest

from tests import helper_tests_analysis as _analysis
from tests import helper_tests_core as _core
from tests import helper_tests_profile_harness as _profile_harness
from tests import helper_tests_multi_launch as _multi_launch
from tests import helper_tests_provenance as _provenance
from tests import helper_tests_report_tilelang as _report_tilelang
from tests import helper_tests_run_evidence as _run_evidence
from tests import helper_tests_simulator_candidate as _simulator_candidate


class HelperTests(
    _core.CoreHelperTests,
    _profile_harness.ProfileHarnessTests,
    _multi_launch.MultiLaunchHelperTests,
    _analysis.AnalysisTests,
    _simulator_candidate.SimulatorCandidateTests,
    _provenance.ProvenanceTests,
    _run_evidence.RunEvidenceTests,
    _report_tilelang.ReportTileLangTests,
):
    """Preserve the historical test class interface across focused modules."""


if __name__ == "__main__":
    unittest.main()
