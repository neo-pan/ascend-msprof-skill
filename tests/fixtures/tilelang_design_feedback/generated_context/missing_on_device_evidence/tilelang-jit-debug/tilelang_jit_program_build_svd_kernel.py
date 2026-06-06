# from tvm.script import tir as T

@T.prim_func
def main(A: T.Buffer((256, 32, 32), "float32"), U: T.Buffer((256, 32, 32), "float32"), S: T.Buffer((256, 32), "float32"), VH: T.Buffer((256, 32, 32), "float32")):
    # with T.block("root"):
    cid = T.launch_thread("blockIdx.x", 256)
    vid = T.launch_thread("blockIdx.y", 2)
    with T.block("tilelang_root"):
        T.reads(A[cid, 0:32, 0:32], U[cid, 0:32, 0:32])
        T.writes(U[cid, 0:32, 0:32], S[cid, 0:32], VH[cid, 0:32, 0:32])
        app = T.handle("float32", "local.var")
        apq = T.handle("float32", "local.var")
        aqq = T.handle("float32", "local.var")
        c = T.handle("float32", "local.var")
        coeff = T.handle("float32", "local.var")
        norm = T.handle("float32", "local.var")
        norm_1 = T.handle("float32", "local.var")
        norm_sq = T.handle("float32", "local.var")
        root = T.handle("float32", "local.var")
        rotate = T.handle("int32", "local.var")
        sigma = T.handle("float32", "local.var")
        sigma_1 = T.handle("float32", "local.var")
        sigma_sq = T.handle("float32", "local.var")
        sign_tau = T.handle("float32", "local.var")
        t = T.handle("float32", "local.var")
        T.block_attr({"tilelang.is_npu_kernel_frame": T.bool(True), "tl.local_var_init": {app: T.float32(0), apq: T.float32(0), aqq: T.float32(0), c: T.float32(1), coeff: T.float32(0), norm: T.float32(1), norm_1: T.float32(1), norm_sq: T.float32(0), root: T.float32(1), rotate: 0, sigma: T.float32(1), sigma_1: T.float32(0), sigma_sq: T.float32(0), sign_tau: T.float32(1), t: T.float32(0)}})
        x_sh = T.alloc_buffer((32, 32), scope="shared.dyn")
        v_sh = T.alloc_buffer((32, 32), scope="shared.dyn")
        sigma_sh = T.alloc_buffer((1, 32), scope="shared.dyn")
        app_1 = T.alloc_buffer((1,), data=app, scope="local.var")
        aqq_1 = T.alloc_buffer((1,), data=aqq, scope="local.var")
        apq_1 = T.alloc_buffer((1,), data=apq, scope="local.var")
        x_kp = T.alloc_buffer((1,), scope="local.var")
        x_kq = T.alloc_buffer((1,), scope="local.var")
        thresh = T.alloc_buffer((1,), scope="local.var")
        rotate_1 = T.alloc_buffer((1,), "int32", data=rotate, scope="local.var")
        tau = T.alloc_buffer((1,), scope="local.var")
        sign_tau_1 = T.alloc_buffer((1,), data=sign_tau, scope="local.var")
        rad = T.alloc_buffer((1,), scope="local.var")
        root_1 = T.alloc_buffer((1,), data=root, scope="local.var")
        denom = T.alloc_buffer((1,), scope="local.var")
        t_1 = T.alloc_buffer((1,), data=t, scope="local.var")
        norm_sq_1 = T.alloc_buffer((1,), scope="local.var")
        norm_2 = T.alloc_buffer((1,), data=norm, scope="local.var")
        c_1 = T.alloc_buffer((1,), data=c, scope="local.var")
        s_rot = T.alloc_buffer((1,), scope="local.var")
        x_kp_1 = T.alloc_buffer((1,), scope="local.var")
        x_kq_1 = T.alloc_buffer((1,), scope="local.var")
        v_kp = T.alloc_buffer((1,), scope="local.var")
        v_kq = T.alloc_buffer((1,), scope="local.var")
        sigma_sq_1 = T.alloc_buffer((1,), data=sigma_sq, scope="local.var")
        x_ij = T.alloc_buffer((1,), scope="local.var")
        sigma_2 = T.alloc_buffer((1,), data=sigma, scope="local.var")
        best_idx = T.alloc_buffer((1,), "int32", scope="local.var")
        best_val = T.alloc_buffer((1,), scope="local.var")
        tmp_s = T.alloc_buffer((1,), scope="local.var")
        tmp_x = T.alloc_buffer((1,), scope="local.var")
        tmp_v = T.alloc_buffer((1,), scope="local.var")
        coeff_1 = T.alloc_buffer((1,), data=coeff, scope="local.var")
        norm_sq_2 = T.alloc_buffer((1,), data=norm_sq, scope="local.var")
        u_ij = T.alloc_buffer((1,), scope="local.var")
        norm_3 = T.alloc_buffer((1,), data=norm_1, scope="local.var")
        sigma_3 = T.alloc_buffer((1,), data=sigma_1, scope="local.var")
        T.attr(0, "resource_scope", 1)
        if vid == 0:
            b: T.int32 = cid
            eps: T.float32 = T.float32(9.9999999999999995e-07)
            sweeps: T.int32 = 12
            for i, j in T.grid(32, 32):
                x_sh[i, j] = A[b, i, j]
                if i == j:
                    v_sh[i, j] = T.float32(1)
                else:
                    v_sh[i, j] = T.float32(0)
            for j in range(32):
                sigma_sh[0, j] = T.float32(0)
            for sweep, p in T.grid(sweeps, 32):
                for q in range(p + 1, p + 1 + (31 - p)):
                    app_1[0] = T.float32(0)
                    aqq_1[0] = T.float32(0)
                    apq_1[0] = T.float32(0)
                    for k in range(32):
                        x_kp[0] = x_sh[k, p]
                        x_kq[0] = x_sh[k, q]
                        x_kp[0] = x_sh[k, p]
                        x_kq[0] = x_sh[k, q]
                        app_1[0] = app_1[0] + x_kp[0] * x_kp[0]
                        aqq_1[0] = aqq_1[0] + x_kq[0] * x_kq[0]
                        apq_1[0] = apq_1[0] + x_kp[0] * x_kq[0]
                    thresh[0] = eps * (app_1[0] + aqq_1[0] + T.float32(1))
                    thresh[0] = eps * (app_1[0] + aqq_1[0] + T.float32(1))
                    rotate_1[0] = 0
                    if apq_1[0] > thresh[0]:
                        rotate_1[0] = 1
                    else:
                        if apq_1[0] < thresh[0] * T.float32(-1):
                            rotate_1[0] = 1
                    if rotate_1[0] != 0:
                        tau[0] = (aqq_1[0] - app_1[0]) / (T.float32(2) * apq_1[0])
                        tau[0] = (aqq_1[0] - app_1[0]) / (T.float32(2) * apq_1[0])
                        if tau[0] < T.float32(0):
                            sign_tau_1[0] = T.float32(-1)
                        else:
                            sign_tau_1[0] = T.float32(1)
                        rad[0] = T.float32(1) + tau[0] * tau[0]
                        rad[0] = T.float32(1) + tau[0] * tau[0]
                        if rad[0] > T.float32(1):
                            root_1[0] = rad[0]
                        else:
                            root_1[0] = T.float32(1)
                        for _ in range(8):
                            root_1[0] = T.float32(0.5) * (root_1[0] + rad[0] / root_1[0])
                        denom[0] = tau[0] + sign_tau_1[0] * root_1[0]
                        denom[0] = tau[0] + sign_tau_1[0] * root_1[0]
                        t_1[0] = T.float32(0)
                        if denom[0] > eps:
                            t_1[0] = T.float32(1) / denom[0]
                        else:
                            if denom[0] < eps * T.float32(-1):
                                t_1[0] = T.float32(1) / denom[0]
                            else:
                                t_1[0] = T.float32(0)
                        norm_sq_1[0] = T.float32(1) + t_1[0] * t_1[0]
                        norm_sq_1[0] = T.float32(1) + t_1[0] * t_1[0]
                        if norm_sq_1[0] > T.float32(1):
                            norm_2[0] = norm_sq_1[0]
                        else:
                            norm_2[0] = T.float32(1)
                        for _ in range(8):
                            norm_2[0] = T.float32(0.5) * (norm_2[0] + norm_sq_1[0] / norm_2[0])
                        c_1[0] = T.float32(1)
                        c_1[0] = c_1[0] / norm_2[0]
                        s_rot[0] = t_1[0] * c_1[0]
                        s_rot[0] = t_1[0] * c_1[0]
                        for k in range(32):
                            x_kp_1[0] = x_sh[k, p]
                            x_kq_1[0] = x_sh[k, q]
                            x_kp_1[0] = x_sh[k, p]
                            x_kq_1[0] = x_sh[k, q]
                            x_sh[k, p] = c_1[0] * x_kp_1[0] - s_rot[0] * x_kq_1[0]
                            x_sh[k, q] = s_rot[0] * x_kp_1[0] + c_1[0] * x_kq_1[0]
                        for k in range(32):
                            v_kp[0] = v_sh[k, p]
                            v_kq[0] = v_sh[k, q]
                            v_kp[0] = v_sh[k, p]
                            v_kq[0] = v_sh[k, q]
                            v_sh[k, p] = c_1[0] * v_kp[0] - s_rot[0] * v_kq[0]
                            v_sh[k, q] = s_rot[0] * v_kp[0] + c_1[0] * v_kq[0]
            for j in range(32):
                sigma_sq_1[0] = T.float32(0)
                for i in range(32):
                    x_ij[0] = x_sh[i, j]
                    x_ij[0] = x_sh[i, j]
                    sigma_sq_1[0] = sigma_sq_1[0] + x_ij[0] * x_ij[0]
                if sigma_sq_1[0] > T.float32(1):
                    sigma_2[0] = sigma_sq_1[0]
                else:
                    sigma_2[0] = T.float32(1)
                for _ in range(8):
                    sigma_2[0] = T.float32(0.5) * (sigma_2[0] + sigma_sq_1[0] / sigma_2[0])
                if sigma_sq_1[0] == T.float32(0):
                    sigma_2[0] = T.float32(0)
                sigma_sh[0, j] = sigma_2[0]
            for i in range(32):
                best_idx[0] = i
                best_val[0] = sigma_sh[0, i]
                best_idx[0] = i
                best_val[0] = sigma_sh[0, i]
                for j in range(i + 1, i + 1 + (31 - i)):
                    if sigma_sh[0, j] > best_val[0]:
                        best_idx[0] = j
                        best_val[0] = sigma_sh[0, j]
                if best_idx[0] != i:
                    tmp_s[0] = sigma_sh[0, i]
                    tmp_s[0] = sigma_sh[0, i]
                    sigma_sh[0, i] = sigma_sh[0, best_idx[0]]
                    sigma_sh[0, best_idx[0]] = tmp_s[0]
                    for k in range(32):
                        tmp_x[0] = x_sh[k, i]
                        tmp_x[0] = x_sh[k, i]
                        x_sh[k, i] = x_sh[k, best_idx[0]]
                        x_sh[k, best_idx[0]] = tmp_x[0]
                    for k in range(32):
                        tmp_v[0] = v_sh[k, i]
                        tmp_v[0] = v_sh[k, i]
                        v_sh[k, i] = v_sh[k, best_idx[0]]
                        v_sh[k, best_idx[0]] = tmp_v[0]
            for i, j in T.grid(32, 32):
                if sigma_sh[0, j] > eps:
                    U[b, i, j] = x_sh[i, j] / sigma_sh[0, j]
                else:
                    U[b, i, j] = T.float32(0)
            for j in range(32):
                for k in range(j):
                    coeff_1[0] = T.float32(0)
                    for i in range(32):
                        coeff_1[0] = coeff_1[0] + U[b, i, k] * U[b, i, j]
                    for i in range(32):
                        U[b, i, j] = U[b, i, j] - coeff_1[0] * U[b, i, k]
                norm_sq_2[0] = T.float32(0)
                for i in range(32):
                    u_ij[0] = U[b, i, j]
                    u_ij[0] = U[b, i, j]
                    norm_sq_2[0] = norm_sq_2[0] + u_ij[0] * u_ij[0]
                if norm_sq_2[0] > T.float32(1):
                    norm_3[0] = norm_sq_2[0]
                else:
                    norm_3[0] = T.float32(1)
                for _ in range(8):
                    norm_3[0] = T.float32(0.5) * (norm_3[0] + norm_sq_2[0] / norm_3[0])
                if norm_3[0] > eps:
                    for i in range(32):
                        U[b, i, j] = U[b, i, j] / norm_3[0]
                else:
                    for i in range(32):
                        U[b, i, j] = T.float32(0)
            for j in range(32):
                sigma_3[0] = T.float32(0)
                for i in range(32):
                    sigma_3[0] = sigma_3[0] + U[b, i, j] * x_sh[i, j]
                sigma_sh[0, j] = sigma_3[0]
                S[b, j] = sigma_3[0]
            for i, j in T.grid(32, 32):
                VH[b, i, j] = v_sh[j, i]
