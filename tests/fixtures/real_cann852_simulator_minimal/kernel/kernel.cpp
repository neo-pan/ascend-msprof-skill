#include "tl_templates/ascend/common.h"
#include "acl/acl.h"
#include <runtime/rt_ffts.h>
using namespace Catlass;
using uint = unsigned int;
using uchar = unsigned char;
using ushort = unsigned short;

extern "C" __global__ __aicore__ void biu_native_vector_kernel( GM_ADDR A_handle,  GM_ADDR B_handle,  GM_ADDR C_handle, uint64_t fftsAddr) {
  KERNEL_TASK_TYPE_DEFAULT(KERNEL_TYPE_AIV_ONLY);
  AscendC::TPipe pipe;

  AscendC::GlobalTensor<float> A;
  A.SetGlobalBuffer((__gm__ float*)A_handle);
  AscendC::GlobalTensor<float> B;
  B.SetGlobalBuffer((__gm__ float*)B_handle);
  AscendC::GlobalTensor<float> C;
  C.SetGlobalBuffer((__gm__ float*)C_handle);

  AscendC::TBuf<AscendC::TPosition::A2> ascend_l0a;
  pipe.InitBuffer(ascend_l0a, 65536);
  AscendC::TBuf<AscendC::TPosition::B2> ascend_l0b;
  pipe.InitBuffer(ascend_l0b, 65536);
  AscendC::TBuf<AscendC::TPosition::A1> ascend_l1; pipe.InitBuffer(ascend_l1, 524032);
  AscendC::TBuf<AscendC::TPosition::CO1> ascend_l0c; pipe.InitBuffer(ascend_l0c, 131072);
  AscendC::TBuf<AscendC::TPosition::VECCALC> ascend_ub; pipe.InitBuffer(ascend_ub, 196352);
  pipe.Destroy();
  auto cid = AscendC::GetBlockIdx();
  auto a = ascend_ub.GetWithOffset<float>(1024, 0);
  auto b = ascend_ub.GetWithOffset<float>(1024, 4096);
  auto vid = AscendC::GetSubBlockIdx();
  if ASCEND_IS_AIV {
    tl::ascend::copy_gm_to_ub<float, 1024, 1>(a[0], A[(cid * 1024)], 49152, 1, 1024, 0.000000e+00f);
    tl::ascend::copy_gm_to_ub<float, 1024, 1>(b[0], B[(cid * 1024)], 49152, 1, 1024, 0.000000e+00f);
    AscendC::PipeBarrier<PIPE_ALL>();
    for (int32_t iteration = 0; iteration < 32; ++iteration) {
      AscendC::Add(a[0], a[0], b[0], 1024);
      AscendC::PipeBarrier<PIPE_ALL>();
    }
    tl::ascend::copy_ub_to_gm<float, 1024, 1>(C[(cid * 1024)], a[0], 49152, 1, 1024);
  }
}

void biu_native_vector_kernel_tiling() {
}

extern "C" void call(uint8_t* A_handle, uint8_t* B_handle, uint8_t* C_handle, aclrtStream stream) {
  uint32_t fftsLen{0};
  uint64_t fftsAddr{0};
  rtGetC2cCtrlAddr(&fftsAddr, &fftsLen);
  biu_native_vector_kernel_tiling();
  biu_native_vector_kernel<<<48, nullptr, stream>>>(A_handle, B_handle, C_handle, fftsAddr);
}
