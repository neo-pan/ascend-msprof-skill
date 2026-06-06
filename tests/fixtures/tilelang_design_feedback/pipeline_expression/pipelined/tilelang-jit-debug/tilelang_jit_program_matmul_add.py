# from tvm.script import tir as T

@T.prim_func
def main(A: T.Buffer((1024, 1024), "float16"), B: T.Buffer((1024, 1024), "float16"), C: T.Buffer((1024, 1024), "float16"), D: T.Buffer((1024, 1024), "float16"), workspace_1: T.Buffer((1024, 1024), "float16")):
    # with T.block("root"):
    cid = T.launch_thread("blockIdx.x", 32)
    vid = T.launch_thread("blockIdx.y", 2)
    with T.block("tilelang_root"):
        loop_k = T.int32()
        T.reads(A[cid // 4 * 128, 0:loop_k * 64 - 63], B[0:loop_k * 64 - 63, cid % 4 * 256], workspace_1[T.min(cid // 4 * 128, cid // 4 * 128 + vid * 64):T.min(cid // 4 * 128, cid // 4 * 128 + vid * 64) + (T.max(cid // 4 * 128, cid // 4 * 128 + vid * 64) + 1 - T.min(cid // 4 * 128, cid // 4 * 128 + vid * 64)), cid % 4 * 256:cid % 4 * 256 + 193], D[cid // 4 * 128 + vid * 128 // 2, cid % 4 * 256:cid % 4 * 256 + 193], C[cid // 4 * 128 + vid * 128 // 2, cid % 4 * 256:cid % 4 * 256 + 193])
        T.writes()
        T.block_attr({"tilelang.is_npu_kernel_frame": T.bool(True)})
        A_L1 = T.alloc_buffer((128, 64), "float16", scope="shared.dyn")
        B_L1 = T.alloc_buffer((64, 256), "float16", scope="shared.dyn")
        C_L0 = T.alloc_buffer((128, 256), scope="local.fragment")
        c_ub = T.alloc_buffer((64, 64), "float16", scope="shared.dyn")
        d_ub = T.alloc_buffer((64, 64), "float16", scope="shared.dyn")
        e_ub = T.alloc_buffer((64, 64), "float16", scope="shared.dyn")
        bx: T.int32 = cid // 4
        by: T.int32 = cid % 4
        with T.LetStmt(16, var=loop_k):
            for kk in T.serial(loop_k, annotations={"num_stages": 3, "tl_cross_interval": 1}):
                T.ascend_copy(T.region(A[bx * 128, kk * 64], 1, 128, 64), T.region(A_L1[0, 0], 2, 128, 64), T.bool(False), T.bool(False), 0)
                T.ascend_copy(T.region(B[kk * 64, by * 256], 1, 64, 256), T.region(B_L1[0, 0], 2, 64, 256), T.bool(False), T.bool(False), 0)
                if kk == 0:
                    T.ascend_gemm_v0("gemm_v0<half, float, 128, 256, 64, false, false>", T.tvm_access_ptr(T.type_annotation("float16"), A_L1.data, 0, 8192, 1), T.tvm_access_ptr(T.type_annotation("float16"), B_L1.data, 0, 16384, 1), T.tvm_access_ptr(T.type_annotation("float32"), C_L0.data, 0, 32768, 2), T.bool(True))
                else:
                    T.ascend_gemm_v0("gemm_v0<half, float, 128, 256, 64, false, false>", T.tvm_access_ptr(T.type_annotation("float16"), A_L1.data, 0, 8192, 1), T.tvm_access_ptr(T.type_annotation("float16"), B_L1.data, 0, 16384, 1), T.tvm_access_ptr(T.type_annotation("float32"), C_L0.data, 0, 32768, 3), T.bool(False))
            T.ascend_copy(T.region(C_L0[0, 0], 1, 128, 256), T.region(workspace_1[bx * 128, by * 256], 2, 128, 256), T.bool(False), T.bool(False), 0)
            for ii in T.serial(4, annotations={"num_stages": 2, "tl_cross_interval": 1}):
                T.ascend_copy(T.region(workspace_1[bx * 128 + vid * 128 // 2, by * 256 + ii * 256 // 4], 1, 64, 64), T.region(c_ub[0, 0], 2, 64, 64), T.bool(False), T.bool(False), 0)
                T.ascend_copy(T.region(D[bx * 128 + vid * 128 // 2, by * 256 + ii * 256 // 4], 1, 64, 64), T.region(d_ub[0, 0], 2, 64, 64), T.bool(False), T.bool(False), 0)
                for jj in T.parallel(64):
                    for kk in T.parallel(64):
                        e_ub[jj, kk] = c_ub[jj, kk] + d_ub[jj, kk]
                T.ascend_copy(T.region(e_ub[0, 0], 1, 64, 64), T.region(C[bx * 128 + vid * 128 // 2, by * 256 + ii * 256 // 4], 2, 64, 64), T.bool(False), T.bool(False), 0)
