#include "tl_templates/ascend/common.h"
#include "acl/acl.h"
#include <runtime/rt_ffts.h>
using namespace Catlass;
using uint = unsigned int;
using uchar = unsigned char;
using ushort = unsigned short;

extern "C" __global__ __aicore__ void main_kernel( GM_ADDR A_handle,  GM_ADDR U_handle,  GM_ADDR S_handle,  GM_ADDR VH_handle, uint64_t fftsAddr) {
  KERNEL_TASK_TYPE_DEFAULT(KERNEL_TYPE_MIX_AIC_1_2);
  AscendC::TPipe pipe;

  AscendC::GlobalTensor<float> A;
  A.SetGlobalBuffer((__gm__ float*)A_handle);
  AscendC::GlobalTensor<float> U;
  U.SetGlobalBuffer((__gm__ float*)U_handle);
  AscendC::GlobalTensor<float> S;
  S.SetGlobalBuffer((__gm__ float*)S_handle);
  AscendC::GlobalTensor<float> VH;
  VH.SetGlobalBuffer((__gm__ float*)VH_handle);

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
  auto x_sh = ascend_ub.GetWithOffset<float>(1024, 0);
  auto v_sh = ascend_l1.GetWithOffset<float>(1024, 0);
  auto sigma_sh = ascend_l1.GetWithOffset<float>(392, 4096);
  float app = 0.000000e+00f;
  float aqq = 0.000000e+00f;
  float apq = 0.000000e+00f;
  float x_kp = 0.000000e+00f;
  float x_kq = 0.000000e+00f;
  float thresh = 0.000000e+00f;
  int rotate = 0;
  float tau = 0.000000e+00f;
  float sign_tau = 1.000000e+00f;
  float rad = 0.000000e+00f;
  float root = 1.000000e+00f;
  float denom = 0.000000e+00f;
  float t = 0.000000e+00f;
  float norm_sq = 0.000000e+00f;
  float norm = 1.000000e+00f;
  float c = 1.000000e+00f;
  float s_rot = 0.000000e+00f;
  float x_kp_1 = 0.000000e+00f;
  float x_kq_1 = 0.000000e+00f;
  float v_kp = 0.000000e+00f;
  float v_kq = 0.000000e+00f;
  float sigma_sq = 0.000000e+00f;
  float x_ij = 0.000000e+00f;
  float sigma = 1.000000e+00f;
  int best_idx = 0;
  float best_val = 0.000000e+00f;
  float tmp_s = 0.000000e+00f;
  float tmp_x = 0.000000e+00f;
  float tmp_v = 0.000000e+00f;
  float coeff = 0.000000e+00f;
  float norm_sq_1 = 0.000000e+00f;
  float u_ij = 0.000000e+00f;
  float norm_1 = 1.000000e+00f;
  float sigma_1 = 0.000000e+00f;
  auto vid = AscendC::GetSubBlockIdx();
  if ASCEND_IS_AIV {
    if (vid == 0) {
      tl::ascend::copy_gm_to_ub<float, 32, 32>(x_sh[0], A[(cid * 1024)], 32, 32, 32, 0.000000e+00f);
      for (int32_t i = 0; i < 32; ++i) {
        for (int32_t j = 0; j < 32; ++j) {
          if (i == j) {
            v_sh.SetValue(((((j / 8) * 256) + (i * 8)) + (j % 8)), 1.000000e+00f);
          } else {
            v_sh.SetValue(((((j / 8) * 256) + (i * 8)) + (j % 8)), 0.000000e+00f);
          }
        }
      }
      for (int32_t j_1 = 0; j_1 < 32; ++j_1) {
        sigma_sh.SetValue((((j_1 / 8) * 128) + (j_1 % 8)), 0.000000e+00f);
      }
      for (int32_t sweep = 0; sweep < 12; ++sweep) {
        for (int32_t p = 0; p < 32; ++p) {
          for (int32_t q = (p + 1); q < 32; ++q) {
            app = 0.000000e+00f;
            aqq = 0.000000e+00f;
            apq = 0.000000e+00f;
            for (int32_t k = 0; k < 32; ++k) {
              x_kp = x_sh.GetValue(((k * 32) + p));
              x_kq = x_sh.GetValue(((k * 32) + q));
              x_kp = x_sh.GetValue(((k * 32) + p));
              x_kq = x_sh.GetValue(((k * 32) + q));
              app = (app + (x_kp * x_kp));
              aqq = (aqq + (x_kq * x_kq));
              apq = (apq + (x_kp * x_kq));
            }
            thresh = (1.000000e-06f * ((app + aqq) + 1.000000e+00f));
            thresh = (1.000000e-06f * ((app + aqq) + 1.000000e+00f));
            rotate = 0;
            if (thresh < apq) {
              rotate = 1;
            } else {
              if (apq < (thresh * -1.000000e+00f)) {
                rotate = 1;
              }
            }
            if (rotate != 0) {
              tau = ((aqq - app) / (2.000000e+00f * apq));
              tau = ((aqq - app) / (2.000000e+00f * apq));
              if (tau < 0.000000e+00f) {
                sign_tau = -1.000000e+00f;
              } else {
                sign_tau = 1.000000e+00f;
              }
              rad = (1.000000e+00f + (tau * tau));
              rad = (1.000000e+00f + (tau * tau));
              if (1.000000e+00f < rad) {
                root = rad;
              } else {
                root = 1.000000e+00f;
              }
              for (int32_t __1 = 0; __1 < 8; ++__1) {
                root = (5.000000e-01f * (root + (rad / root)));
              }
              denom = (tau + (sign_tau * root));
              denom = (tau + (sign_tau * root));
              t = 0.000000e+00f;
              if (1.000000e-06f < denom) {
                t = (1.000000e+00f / denom);
              } else {
                if (denom < -1.000000e-06f) {
                  t = (1.000000e+00f / denom);
                } else {
                  t = 0.000000e+00f;
                }
              }
              norm_sq = (1.000000e+00f + (t * t));
              norm_sq = (1.000000e+00f + (t * t));
              if (1.000000e+00f < norm_sq) {
                norm = norm_sq;
              } else {
                norm = 1.000000e+00f;
              }
              for (int32_t __2 = 0; __2 < 8; ++__2) {
                norm = (5.000000e-01f * (norm + (norm_sq / norm)));
              }
              c = 1.000000e+00f;
              c = (c / norm);
              s_rot = (t * c);
              s_rot = (t * c);
              for (int32_t k_1 = 0; k_1 < 32; ++k_1) {
                x_kp_1 = x_sh.GetValue(((k_1 * 32) + p));
                x_kq_1 = x_sh.GetValue(((k_1 * 32) + q));
                x_kp_1 = x_sh.GetValue(((k_1 * 32) + p));
                x_kq_1 = x_sh.GetValue(((k_1 * 32) + q));
                x_sh.SetValue(((k_1 * 32) + p), ((c * x_kp_1) - (s_rot * x_kq_1)));
                x_sh.SetValue(((k_1 * 32) + q), ((s_rot * x_kp_1) + (c * x_kq_1)));
              }
              for (int32_t k_2 = 0; k_2 < 32; ++k_2) {
                v_kp = v_sh.GetValue(((((p / 8) * 256) + (k_2 * 8)) + (p % 8)));
                v_kq = v_sh.GetValue(((((q / 8) * 256) + (k_2 * 8)) + (q % 8)));
                v_kp = v_sh.GetValue(((((p / 8) * 256) + (k_2 * 8)) + (p % 8)));
                v_kq = v_sh.GetValue(((((q / 8) * 256) + (k_2 * 8)) + (q % 8)));
                v_sh.SetValue(((((p / 8) * 256) + (k_2 * 8)) + (p % 8)), ((c * v_kp) - (s_rot * v_kq)));
                v_sh.SetValue(((((q / 8) * 256) + (k_2 * 8)) + (q % 8)), ((s_rot * v_kp) + (c * v_kq)));
              }
            }
          }
        }
      }
      for (int32_t j_2 = 0; j_2 < 32; ++j_2) {
        sigma_sq = 0.000000e+00f;
        for (int32_t i_1 = 0; i_1 < 32; ++i_1) {
          x_ij = x_sh.GetValue(((i_1 * 32) + j_2));
          x_ij = x_sh.GetValue(((i_1 * 32) + j_2));
          sigma_sq = (sigma_sq + (x_ij * x_ij));
        }
        if (1.000000e+00f < sigma_sq) {
          sigma = sigma_sq;
        } else {
          sigma = 1.000000e+00f;
        }
        for (int32_t __3 = 0; __3 < 8; ++__3) {
          sigma = (5.000000e-01f * (sigma + (sigma_sq / sigma)));
        }
        if (sigma_sq == 0.000000e+00f) {
          sigma = 0.000000e+00f;
        }
        sigma_sh.SetValue((((j_2 / 8) * 128) + (j_2 % 8)), sigma);
      }
      for (int32_t i_2 = 0; i_2 < 32; ++i_2) {
        best_idx = i_2;
        best_val = sigma_sh.GetValue((((i_2 / 8) * 128) + (i_2 % 8)));
        best_idx = i_2;
        best_val = sigma_sh.GetValue((((i_2 / 8) * 128) + (i_2 % 8)));
        for (int32_t j_3 = (i_2 + 1); j_3 < 32; ++j_3) {
          if (best_val < sigma_sh.GetValue((((j_3 / 8) * 128) + (j_3 % 8)))) {
            best_idx = j_3;
            best_val = sigma_sh.GetValue((((j_3 / 8) * 128) + (j_3 % 8)));
          }
        }
        if (best_idx != i_2) {
          tmp_s = sigma_sh.GetValue((((i_2 / 8) * 128) + (i_2 % 8)));
          tmp_s = sigma_sh.GetValue((((i_2 / 8) * 128) + (i_2 % 8)));
          sigma_sh.SetValue((((i_2 / 8) * 128) + (i_2 % 8)), sigma_sh.GetValue((((((int64_t)best_idx) / (int64_t)8) * (int64_t)128) + (((int64_t)best_idx) % (int64_t)8))));
          sigma_sh.SetValue((((((int64_t)best_idx) / (int64_t)8) * (int64_t)128) + (((int64_t)best_idx) % (int64_t)8)), tmp_s);
          for (int32_t k_3 = 0; k_3 < 32; ++k_3) {
            tmp_x = x_sh.GetValue(((k_3 * 32) + i_2));
            tmp_x = x_sh.GetValue(((k_3 * 32) + i_2));
            x_sh.SetValue(((k_3 * 32) + i_2), x_sh.GetValue(((((int64_t)k_3) * (int64_t)32) + ((int64_t)best_idx))));
            x_sh.SetValue(((((int64_t)k_3) * (int64_t)32) + ((int64_t)best_idx)), tmp_x);
          }
          for (int32_t k_4 = 0; k_4 < 32; ++k_4) {
            tmp_v = v_sh.GetValue(((((i_2 / 8) * 256) + (k_4 * 8)) + (i_2 % 8)));
            tmp_v = v_sh.GetValue(((((i_2 / 8) * 256) + (k_4 * 8)) + (i_2 % 8)));
            v_sh.SetValue(((((i_2 / 8) * 256) + (k_4 * 8)) + (i_2 % 8)), v_sh.GetValue(((((((int64_t)best_idx) / (int64_t)8) * (int64_t)256) + (((int64_t)k_4) * (int64_t)8)) + (((int64_t)best_idx) % (int64_t)8))));
            v_sh.SetValue(((((((int64_t)best_idx) / (int64_t)8) * (int64_t)256) + (((int64_t)k_4) * (int64_t)8)) + (((int64_t)best_idx) % (int64_t)8)), tmp_v);
          }
        }
      }
      for (int32_t i_3 = 0; i_3 < 32; ++i_3) {
        for (int32_t j_4 = 0; j_4 < 32; ++j_4) {
          if (1.000000e-06f < sigma_sh.GetValue((((j_4 / 8) * 128) + (j_4 % 8)))) {
            U.SetValue((((cid * 1024) + (i_3 * 32)) + j_4), (x_sh.GetValue(((i_3 * 32) + j_4)) / sigma_sh.GetValue((((j_4 / 8) * 128) + (j_4 % 8)))));
          } else {
            U.SetValue((((cid * 1024) + (i_3 * 32)) + j_4), 0.000000e+00f);
          }
        }
      }
      for (int32_t j_5 = 0; j_5 < 32; ++j_5) {
        for (int32_t k_5 = 0; k_5 < j_5; ++k_5) {
          coeff = 0.000000e+00f;
          for (int32_t i_4 = 0; i_4 < 32; ++i_4) {
            coeff = (coeff + (U.GetValue((((cid * 1024) + (i_4 * 32)) + k_5)) * U.GetValue((((cid * 1024) + (i_4 * 32)) + j_5))));
          }
          for (int32_t i_5 = 0; i_5 < 32; ++i_5) {
            U.SetValue((((cid * 1024) + (i_5 * 32)) + j_5), (U.GetValue((((cid * 1024) + (i_5 * 32)) + j_5)) - (coeff * U.GetValue((((cid * 1024) + (i_5 * 32)) + k_5)))));
          }
        }
        norm_sq_1 = 0.000000e+00f;
        for (int32_t i_6 = 0; i_6 < 32; ++i_6) {
          u_ij = U.GetValue((((cid * 1024) + (i_6 * 32)) + j_5));
          u_ij = U.GetValue((((cid * 1024) + (i_6 * 32)) + j_5));
          norm_sq_1 = (norm_sq_1 + (u_ij * u_ij));
        }
        if (1.000000e+00f < norm_sq_1) {
          norm_1 = norm_sq_1;
        } else {
          norm_1 = 1.000000e+00f;
        }
        for (int32_t __4 = 0; __4 < 8; ++__4) {
          norm_1 = (5.000000e-01f * (norm_1 + (norm_sq_1 / norm_1)));
        }
        if (1.000000e-06f < norm_1) {
          for (int32_t i_7 = 0; i_7 < 32; ++i_7) {
            U.SetValue((((cid * 1024) + (i_7 * 32)) + j_5), (U.GetValue((((cid * 1024) + (i_7 * 32)) + j_5)) / norm_1));
          }
        } else {
          for (int32_t i_8 = 0; i_8 < 32; ++i_8) {
            U.SetValue((((cid * 1024) + (i_8 * 32)) + j_5), 0.000000e+00f);
          }
        }
      }
      for (int32_t j_6 = 0; j_6 < 32; ++j_6) {
        sigma_1 = 0.000000e+00f;
        for (int32_t i_9 = 0; i_9 < 32; ++i_9) {
          sigma_1 = (sigma_1 + (U.GetValue((((cid * 1024) + (i_9 * 32)) + j_6)) * x_sh.GetValue(((i_9 * 32) + j_6))));
        }
        sigma_sh.SetValue((((j_6 / 8) * 128) + (j_6 % 8)), sigma_1);
        S.SetValue(((cid * 32) + j_6), sigma_1);
      }
      for (int32_t i_10 = 0; i_10 < 32; ++i_10) {
        for (int32_t j_7 = 0; j_7 < 32; ++j_7) {
          VH.SetValue((((cid * 1024) + (i_10 * 32)) + j_7), v_sh.GetValue(((((i_10 / 8) * 256) + (j_7 * 8)) + (i_10 % 8))));
        }
      }
    }
  }
}

void main_kernel_tiling() {
}

extern "C" void call(uint8_t* A_handle, uint8_t* U_handle, uint8_t* S_handle, uint8_t* VH_handle, aclrtStream stream) {
  uint32_t fftsLen{0};
  uint64_t fftsAddr{0};
  rtGetC2cCtrlAddr(&fftsAddr, &fftsLen);
  main_kernel_tiling();
  main_kernel<<<256, nullptr, stream>>>(A_handle, U_handle, S_handle, VH_handle, fftsAddr);
}

