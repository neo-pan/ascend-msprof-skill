#include "tl_templates/ascend/common.h"
#include "acl/acl.h"
#include <runtime/rt_ffts.h>
using namespace Catlass;
using uint = unsigned int;
using uchar = unsigned char;
using ushort = unsigned short;

extern "C" __global__ __aicore__ void main_kernel( GM_ADDR A_handle,  GM_ADDR B_handle,  GM_ADDR C_handle,  GM_ADDR D_handle,  GM_ADDR workspace_1_handle, uint64_t fftsAddr) {
  KERNEL_TASK_TYPE_DEFAULT(KERNEL_TYPE_MIX_AIC_1_2);
  AscendC::TPipe pipe;

  AscendC::GlobalTensor<half> A;
  A.SetGlobalBuffer((__gm__ half*)A_handle);
  AscendC::GlobalTensor<half> B;
  B.SetGlobalBuffer((__gm__ half*)B_handle);
  AscendC::GlobalTensor<half> C;
  C.SetGlobalBuffer((__gm__ half*)C_handle);
  AscendC::GlobalTensor<half> D;
  D.SetGlobalBuffer((__gm__ half*)D_handle);
  AscendC::GlobalTensor<half> workspace_1;
  workspace_1.SetGlobalBuffer((__gm__ half*)workspace_1_handle);

  AscendC::TBuf<AscendC::TPosition::A2> ascend_l0a;
  pipe.InitBuffer(ascend_l0a, 65536);
  AscendC::TBuf<AscendC::TPosition::B2> ascend_l0b;
  pipe.InitBuffer(ascend_l0b, 65536);
  AscendC::TBuf<AscendC::TPosition::A1> ascend_l1; pipe.InitBuffer(ascend_l1, 524032);
  AscendC::TBuf<AscendC::TPosition::CO1> ascend_l0c; pipe.InitBuffer(ascend_l0c, 131072);
  AscendC::TBuf<AscendC::TPosition::VECCALC> ascend_ub; pipe.InitBuffer(ascend_ub, 196352);
  pipe.Destroy();
  auto cid = AscendC::GetBlockIdx();
  if ASCEND_IS_AIV {
    cid = cid / 2;
  }
  auto A_L1 = ascend_l1.GetWithOffset<half>(24576, 0);
  auto B_L1 = ascend_l1.GetWithOffset<half>(49152, 49152);
  auto C_L0 = ascend_l0c.GetWithOffset<float>(32768, 0);
  auto c_ub = ascend_ub.GetWithOffset<half>(8192, 0);
  auto d_ub = ascend_ub.GetWithOffset<half>(8192, 16384);
  auto e_ub = ascend_ub.GetWithOffset<half>(4096, 32768);
  auto vid = AscendC::GetSubBlockIdx();
  if ASCEND_IS_AIC {
    tl::ascend::copy_gm_to_l1<half, 128, 64>(A_L1[0], A[((cid / 4) * 131072)], 1024, 128, 64);
    tl::ascend::copy_gm_to_l1<half, 64, 256>(B_L1[0], B[((cid % 4) * 256)], 1024, 64, 256);
    AscendC::PipeBarrier<PIPE_MTE2>();
    tl::ascend::copy_gm_to_l1<half, 128, 64>(A_L1[8192], A[(((cid / 4) * 131072) + 64)], 1024, 128, 64);
    tl::ascend::copy_gm_to_l1<half, 64, 256>(B_L1[16384], B[(((cid % 4) * 256) + 65536)], 1024, 64, 256);
    for (int32_t kk = 0; kk < 14; ++kk) {
      AscendC::PipeBarrier<PIPE_MTE2>();
      tl::ascend::copy_gm_to_l1<half, 128, 64>(A_L1[(((kk + 2) % 3) * 8192)], A[((((cid / 4) * 131072) + (kk * 64)) + 128)], 1024, 128, 64);
      tl::ascend::copy_gm_to_l1<half, 64, 256>(B_L1[(((kk + 2) % 3) * 16384)], B[(((kk * 65536) + ((cid % 4) * 256)) + 131072)], 1024, 64, 256);
      AscendC::PipeBarrier<PIPE_ALL>();
      if (kk == 0) {
        tl::ascend::gemm_v0<half, float, 128, 256, 64, false, false>(A_L1[(kk * 8192)], B_L1[(kk * 16384)], C_L0[0], ascend_l0a, ascend_l0b, (bool)1);
      } else {
        tl::ascend::gemm_v0<half, float, 128, 256, 64, false, false>(A_L1[((kk % 3) * 8192)], B_L1[((kk % 3) * 16384)], C_L0[0], ascend_l0a, ascend_l0b, (bool)0);
      }
      AscendC::PipeBarrier<PIPE_ALL>();
      AscendC::PipeBarrier<PIPE_ALL>();
    }
    tl::ascend::gemm_v0<half, float, 128, 256, 64, false, false>(A_L1[16384], B_L1[32768], C_L0[0], ascend_l0a, ascend_l0b, (bool)0);
    AscendC::PipeBarrier<PIPE_M>();
    tl::ascend::gemm_v0<half, float, 128, 256, 64, false, false>(A_L1[0], B_L1[0], C_L0[0], ascend_l0a, ascend_l0b, (bool)0);
    AscendC::SetFlag<AscendC::HardEvent::M_FIX>(1);
    AscendC::WaitFlag<AscendC::HardEvent::M_FIX>(1);
    tl::ascend::copy_l0c_to_gm<float, half, layout::RowMajor, 128, 256, 0>(workspace_1[(((cid / 4) * 131072) + ((cid % 4) * 256))], C_L0[0], 1024, 128, 256);
    AscendC::CrossCoreSetFlag<2, PIPE_FIX>(0);
  }
  if ASCEND_IS_AIV {
    AscendC::CrossCoreWaitFlag(0);
    tl::ascend::copy_gm_to_ub<half, 64, 64>(c_ub[0], workspace_1[((((cid / 4) * 131072) + (vid * 65536)) + ((cid % 4) * 256))], 1024, 64, 64, half(0.000000e+00f));
    tl::ascend::copy_gm_to_ub<half, 64, 64>(d_ub[0], D[((((cid / 4) * 131072) + (vid * 65536)) + ((cid % 4) * 256))], 1024, 64, 64, half(0.000000e+00f));
    AscendC::PipeBarrier<PIPE_MTE2>();
    tl::ascend::copy_gm_to_ub<half, 64, 64>(c_ub[4096], workspace_1[(((((cid / 4) * 131072) + (vid * 65536)) + ((cid % 4) * 256)) + 64)], 1024, 64, 64, half(0.000000e+00f));
    tl::ascend::copy_gm_to_ub<half, 64, 64>(d_ub[4096], D[(((((cid / 4) * 131072) + (vid * 65536)) + ((cid % 4) * 256)) + 64)], 1024, 64, 64, half(0.000000e+00f));
    for (int32_t ii = 0; ii < 2; ++ii) {
      AscendC::SetFlag<AscendC::HardEvent::MTE2_V>(2);
      AscendC::WaitFlag<AscendC::HardEvent::MTE2_V>(2);
      AscendC::SetFlag<AscendC::HardEvent::MTE3_V>(6);
      AscendC::WaitFlag<AscendC::HardEvent::MTE3_V>(6);
      AscendC::Add(e_ub[0], c_ub[(ii * 4096)], d_ub[(ii * 4096)], 4096);
      AscendC::SetFlag<AscendC::HardEvent::V_MTE2>(3);
      AscendC::WaitFlag<AscendC::HardEvent::V_MTE2>(3);
      tl::ascend::copy_gm_to_ub<half, 64, 64>(c_ub[(ii * 4096)], workspace_1[((((((cid / 4) * 131072) + (vid * 65536)) + ((cid % 4) * 256)) + (ii * 64)) + 128)], 1024, 64, 64, half(0.000000e+00f));
      tl::ascend::copy_gm_to_ub<half, 64, 64>(d_ub[(ii * 4096)], D[((((((cid / 4) * 131072) + (vid * 65536)) + ((cid % 4) * 256)) + (ii * 64)) + 128)], 1024, 64, 64, half(0.000000e+00f));
      AscendC::SetFlag<AscendC::HardEvent::V_MTE3>(4);
      AscendC::WaitFlag<AscendC::HardEvent::V_MTE3>(4);
      AscendC::PipeBarrier<PIPE_MTE3>();
      tl::ascend::copy_ub_to_gm<half, 64, 64>(C[(((((cid / 4) * 131072) + (vid * 65536)) + ((cid % 4) * 256)) + (ii * 64))], e_ub[0], 1024, 64, 64);
    }
    AscendC::SetFlag<AscendC::HardEvent::MTE2_V>(1);
    AscendC::WaitFlag<AscendC::HardEvent::MTE2_V>(1);
    AscendC::SetFlag<AscendC::HardEvent::MTE3_V>(2);
    AscendC::WaitFlag<AscendC::HardEvent::MTE3_V>(2);
    AscendC::Add(e_ub[0], c_ub[0], d_ub[0], 4096);
    AscendC::SetFlag<AscendC::HardEvent::V_MTE3>(3);
    AscendC::WaitFlag<AscendC::HardEvent::V_MTE3>(3);
    AscendC::PipeBarrier<PIPE_MTE3>();
    tl::ascend::copy_ub_to_gm<half, 64, 64>(C[(((((cid / 4) * 131072) + (vid * 65536)) + ((cid % 4) * 256)) + 128)], e_ub[0], 1024, 64, 64);
    AscendC::SetFlag<AscendC::HardEvent::MTE3_V>(4);
    AscendC::WaitFlag<AscendC::HardEvent::MTE3_V>(4);
    AscendC::Add(e_ub[0], c_ub[4096], d_ub[4096], 4096);
    AscendC::SetFlag<AscendC::HardEvent::V_MTE3>(5);
    AscendC::WaitFlag<AscendC::HardEvent::V_MTE3>(5);
    AscendC::PipeBarrier<PIPE_MTE3>();
    tl::ascend::copy_ub_to_gm<half, 64, 64>(C[(((((cid / 4) * 131072) + (vid * 65536)) + ((cid % 4) * 256)) + 192)], e_ub[0], 1024, 64, 64);
  }
}

void main_kernel_tiling() {
}

extern "C" void call(uint8_t* A_handle, uint8_t* B_handle, uint8_t* C_handle, uint8_t* D_handle, uint8_t* workspace_1_handle, aclrtStream stream) {
  uint32_t fftsLen{0};
  uint64_t fftsAddr{0};
  rtGetC2cCtrlAddr(&fftsAddr, &fftsLen);
  main_kernel_tiling();
  main_kernel<<<32, nullptr, stream>>>(A_handle, B_handle, C_handle, D_handle, workspace_1_handle, fftsAddr);
}

