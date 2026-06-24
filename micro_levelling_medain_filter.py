import re
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

def _odd(n: int) -> int:
    """Return n rounded up to the nearest odd integer."""
    n = int(max(1, n))
    return n if n % 2 == 1 else n + 1


def roll_med(x, w):
    """
    Centered rolling median with min_periods=1.
    NaN-safe because pandas median skips NaN automatically.
    """
    if w <= 1:
        return np.asarray(x, dtype=float)
    s = pd.Series(x, dtype=float)
    return s.rolling(window=_odd(int(w)), center=True, min_periods=1).median().to_numpy()


def resolve_line_col(df, line_col=None):
    """
    Find the line column name in df. Defaults to 'Line' or variants.
    """
    cols = list(df.columns)
    if line_col is not None:
        if line_col in cols:
            return line_col
        for c in cols:
            if c.lower() == str(line_col).lower():
                return c
        raise KeyError(f"line_col '{line_col}' not found. Available columns: {cols}")

    if "Line" in cols:
        return "Line"
    for c in cols:
        if c.lower() == "line":
            return c

    def norm(s):
        return re.sub(r"[^a-z0-9]+", "", s.lower())

    normalized = {norm(c): c for c in cols}
    aliases = [
        "lineno",
        "line_no",
        "lineid",
        "line_id",
        "linenumber",
        "line_num",
        "linenum",
        "lineindex",
        "line_idx",
    ]
    for a in aliases:
        a_norm = norm(a)
        if a_norm in normalized:
            return normalized[a_norm]

    token_matches = []
    for c in cols:
        tokens = [t for t in re.split(r"[^a-z0-9]+", c.lower()) if t]
        if "line" in tokens:
            token_matches.append(c)
    if len(token_matches) == 1:
        return token_matches[0]
    if len(token_matches) > 1:
        raise KeyError(
            f"Multiple possible line columns: {token_matches}. Pass line_col explicitly."
        )
    raise KeyError(f"No 'Line' column found. Available columns: {cols}")


def estimate_spacing(df, line_col=None):
    """
    Estimate median sample spacing (meters) across lines using E,N columns.
    """
    vals = []
    line_col = resolve_line_col(df, line_col=line_col)
    for _, g in df.groupby(line_col, sort=False):
        xy = g[["E", "N"]].to_numpy(float)
        if len(xy) < 2:
            continue
        dxy = np.sqrt(np.sum((xy[1:] - xy[:-1]) ** 2, axis=1))
        if len(dxy):
            vals.append(np.nanmedian(dxy))
    return float(np.nanmedian(vals)) if vals else 5.0


def win_pts(Lm, spacing):
    """
    Convert window length (meters) to sample count, rounded to odd.
    """
    return _odd(int((2.0 * Lm / spacing) + 1.0)) if spacing > 0 else 1


def median2d_on(values, E, N, r_m, min_neighbors=5):
    """
    Spatial median around each point within radius r_m using E,N coordinates.
    """
    values = np.asarray(values, float)
    E = np.asarray(E, float)
    N = np.asarray(N, float)

    # NaN coordinates would corrupt cKDTree's spatial partitioning, returning
    # garbage neighbours even for valid points. Build the tree from finite
    # coordinates only and fall back to the raw value for NaN-coordinate points.
    coords = np.column_stack([E, N])
    valid = np.isfinite(E) & np.isfinite(N)
    out = np.array(values, float)
    if not valid.any():
        return out

    valid_idx = np.flatnonzero(valid)
    tree = cKDTree(coords[valid_idx])
    for i in valid_idx:
        neigh_local = tree.query_ball_point(coords[i], r=float(r_m))
        if not neigh_local:
            out[i] = values[i]
            continue
        neigh = valid_idx[neigh_local]
        arr = values[neigh]
        finite = np.isfinite(arr)
        if finite.sum() < min_neighbors:
            out[i] = values[i]
        else:
            out[i] = float(np.nanmedian(arr[finite]))
    return out


def run_micro_level(scanline_df, w_short, w_long, r_m, min_neigh, col_name):
    """
    Apply micro-levelling to each scanline dataframe in the dict.

    泥섎━ ?쒖꽌:
      1) 媛??쇱씤(?뺤뀛?덈━ item)蹂꾨줈 mag_rc, mag_1D 怨꾩궛
      2) 紐⑤뱺 ?쇱씤????踰덉뿉 ?⑹퀜??mag_2D(2D 誘몃뵒?? 怨꾩궛
      3) ?ㅼ떆 ?쇱씤蹂꾨줈 遺꾨━??corr, mag_level ?묒꽦

    LINE 而щ읆 ?놁씠 dict item ?섎굹媛� ???쇱씤?쇰줈 媛꾩＜?쒕떎.
    異붽? 而щ읆: mag_rc, mag_1D, mag_2D, corr, mag_level
    """
    # 1) per-line 1D 泥섎━
    prepared = []
    keys = []
    for key, df in scanline_df.items():
        keys.append(key)
        if df is None or df.empty:
            prepared.append(df)
            continue
        if not {"X", "Y"}.issubset(df.columns):
            raise KeyError("run_micro_level requires X and Y columns.")

        work = df.copy()
        sens_col = col_name
        sens = pd.to_numeric(work[sens_col], errors="coerce").to_numpy(float)

        work["mag_rc"] = roll_med(sens, w_short)
        work["mag_1D"] = roll_med(work["mag_rc"].to_numpy(float), w_long)
        prepared.append(work)

    # 2) 紐⑤뱺 ?쇱씤 ?⑹퀜??2D median ?ㅽ뻾
    concat_df = pd.concat(
        prepared, keys=keys, names=["scanline", "orig_idx"], axis=0, copy=False
    )
    if concat_df.empty:
        return {k: v for k, v in zip(keys, prepared)}

    concat_df["mag_2D"] = median2d_on(
        concat_df["mag_rc"].to_numpy(float),
        pd.to_numeric(concat_df["X"], errors="coerce").to_numpy(float),
        pd.to_numeric(concat_df["Y"], errors="coerce").to_numpy(float),
        r_m=r_m,
        min_neighbors=min_neigh,
    )

    # 3) corr, mag_level ?묒꽦 ???ㅼ떆 遺꾪븷
    concat_df["corr"] = concat_df["mag_2D"] - concat_df["mag_1D"]
    concat_df["Mag_Level"] = concat_df["mag_rc"] + concat_df["corr"]
    # drop intermediate columns; keep mag_level plus original fields
    concat_df = concat_df.drop(columns=["mag_rc", "mag_1D", "mag_2D", "corr"], errors="ignore")
    # ensure Mag_Level is the last column
    cols = [c for c in concat_df.columns if c != "Mag_Level"] + ["Mag_Level"]
    concat_df = concat_df[cols]

    out = {}
    for key in keys:
        part = concat_df.xs(key, level="scanline").copy()
        out[key] = part
    return out
