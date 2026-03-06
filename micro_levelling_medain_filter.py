import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
import re
from loguru import logger

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
    coords = np.column_stack([E, N])
    tree = cKDTree(coords)
    out = np.empty(len(values), float)
    for i in range(len(values)):
        neigh = tree.query_ball_point(coords[i], r=float(r_m))
        if not neigh:
            out[i] = values[i]
            continue
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

    처리 순서:
      1) 각 라인(딕셔너리 item)별로 mag_rc, mag_1D 계산
      2) 모든 라인을 한 번에 합쳐서 mag_2D(2D 미디언) 계산
      3) 다시 라인별로 분리해 corr, mag_level 작성

    LINE 컬럼 없이 dict item 하나가 한 라인으로 간주된다.
    추가 컬럼: mag_rc, mag_1D, mag_2D, corr, mag_level
    """
    # 1) per-line 1D 처리
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
        # sens_col = work.columns[-1]  # 마지막 컬럼을 신호로 사용
        sens_col = col_name
        logger.debug(f"Processing scanline '{key}' with signal column '{sens_col}'")
        sens = pd.to_numeric(work[sens_col], errors="coerce").to_numpy(float)

        work["mag_rc"] = roll_med(sens, w_short)
        work["mag_1D"] = roll_med(work["mag_rc"].to_numpy(float), w_long)
        prepared.append(work)

    # 2) 모든 라인 합쳐서 2D median 실행
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

    # 3) corr, mag_level 작성 후 다시 분할
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
    logger.debug(f"Completed micro-levelling for {len(out)} scanlines.")
    return out
