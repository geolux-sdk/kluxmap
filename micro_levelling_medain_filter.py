import numpy as np, pandas as pd
from scipy.spatial import cKDTree
import re

def _odd(n):
    """
    주어진 정수를 1 이상의 홀수로 보정.

    Parameters
    ----------
    n : int
        창 길이 후보.

    Returns
    -------
    int
        1 이상인 홀수 길이.
    """
    n = int(max(1, n))
    return n if n % 2 == 1 else n + 1


def roll_med(x, w):
    """
    중심 정렬(center=True)된 **롤링 중앙값**을 계산.

    - 가장자리에서도 `min_periods=1`로 동작하므로 길이 부족 구간도 처리됨.
    - NaN이 섞여 있어도 pandas의 median이 자동으로 무시하고 계산.

    Parameters
    ----------
    x : array-like (1D)
        신호(예: 라인 위 측정값).
    w : int
        창 길이(포인트 단위). 짝수가 들어와도 내부에서 홀수로 보정됨.

    Returns
    -------
    np.ndarray
        동일 길이의 중앙값 시퀀스.
    """
    if w <= 1:
        return x.astype(float)
    s = pd.Series(x, dtype=float)
    return s.rolling(window=_odd(int(w)), center=True, min_periods=1).median().to_numpy()


def resolve_line_col(df, line_col=None):
    """
    df에서 라인 컬럼명을 찾아 반환.
    - 기본은 'Line' (대소문자 무시)와 흔한 별칭을 자동 매칭.
    - 모호하면 명시적으로 line_col을 넘기도록 오류를 냄.
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
        "lineno", "line_no", "lineid", "line_id", "linenumber",
        "line_num", "linenum", "lineindex", "line_idx"
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
        raise KeyError(f"Multiple possible line columns: {token_matches}. Pass line_col explicitly.")
    raise KeyError(f"No 'Line' column found. Available columns: {cols}")


def estimate_spacing(df, line_col=None):
    """
    라인별 연속 샘플 간 거리의 **중앙값**을 구해, 전체에 대한 대표 **샘플 간격(미터)**을 추정.

    - 각 라인에서 (E,N) 좌표의 1-차 차분 거리들의 중앙값을 구하고,
      모든 라인의 중앙값들의 중앙값을 대표값으로 반환.
    - 좌표는 미터(또는 동일 단위)여야 함.

    Parameters
    ----------
    df : pandas.DataFrame
        최소한 다음 컬럼을 포함해야 함: 'Line', 'E', 'N'.

    Returns
    -------
    float
        추정된 샘플 간격(미터). 라인 데이터가 부족하면 5.0을 반환.
    """
    vals = []
    line_col = resolve_line_col(df, line_col=line_col)
    for _, g in df.groupby(line_col, sort=False):
        xy = g[["E","N"]].to_numpy(float)
        if len(xy) < 2:
            continue
        dxy = np.sqrt(np.sum((xy[1:] - xy[:-1])**2, axis=1))
        if len(dxy):
            vals.append(np.nanmedian(dxy))
    return float(np.nanmedian(vals)) if vals else 5.0


def win_pts(Lm, spacing):
    """
    물리 길이(Lm, 미터)를 **포인트 창 길이**로 변환.

    - 창은 ±(Lm) 범위를 덮는 길이로 산정: `2*Lm/spacing + 1`
    - 결과는 홀수로 보정됨.

    Parameters
    ----------
    Lm : float
        물리 창 길이(미터 단위의 반폭 아님! 여기서는 전체 길이).
    spacing : float
        샘플 간격(미터).

    Returns
    -------
    int
        포인트 단위 창 길이(홀수).
    """
    return _odd(int((2.0 * Lm / spacing) + 1.0)) if spacing > 0 else 1


def median2d_on(values, E, N, r_m, min_neighbors=5):
    """
    (E,N) 평면에서 반경 r_m 내 이웃들을 사용한 **2D 이동 중앙값**.

    - 각 점 i에 대해 반경 r_m(미터) 원 내부의 이웃 인덱스를 수집하고,
      해당 이웃들의 `values` 중앙값을 반환.
    - 유효 이웃 수가 `min_neighbors` 미만이면 자기 자신의 값을 그대로 사용
      (희소/가장자리에서의 과보정 방지).
    - 내부 구현은 `scipy.spatial.cKDTree.query_ball_point` 사용.

    Parameters
    ----------
    values : array-like (1D)
        보간 대상 값(예: RC 후 신호, detrended 값 등).
    E, N : array-like (1D)
        동/북좌표(미터). 길이는 values와 동일해야 함.
    r_m : float
        검색 반경(미터). 일반적으로 라인 간격의 3~4배 근처를 권장.
    min_neighbors : int, default=5
        중앙값을 계산하기 위한 최소 유효 이웃 수. 작을수록 공격적, 클수록 보수적.

    Returns
    -------
    np.ndarray
        각 점의 2D 이동 중앙값 배열.
    """
    coords = np.column_stack([E, N])
    tree = cKDTree(coords)
    out = np.empty(len(values), float)
    for i in range(len(values)):
        neigh = tree.query_ball_point(coords[i], r=float(r_m))
        if not neigh:  # 이웃이 전혀 없으면 자기 자신
            out[i] = values[i]
            continue
        arr = values[neigh]
        finite = np.isfinite(arr)
        if finite.sum() < min_neighbors:
            out[i] = values[i]
        else:
            out[i] = float(np.nanmedian(arr[finite]))
    return out

def run_micro_level(filtered_mag, df, short_len, long_len, search_radius, min_neighbors):
    # 1) 짧은 창 rc
    sens = df["Sensor_Total"].to_numpy(float)
    df["mag_rc"]  = 0.0
    for lv, idx in df.groupby(line_col, sort=False).groups.items():
        idx = np.asarray(list(idx), dtype=int)
        df.loc[idx, "mag_rc"] = roll_med(sens[idx], w_short)

    # 2) 긴 창 m1D (rc 위에)
    df["mag_1D"] = 0.0
    for lv, idx in df.groupby(line_col, sort=False).groups.items():
        idx = np.asarray(list(idx), dtype=int)
        df.loc[idx, "mag_1D"] = roll_med(df.loc[idx,"mag_rc"].to_numpy(float), w_long)

    # 3) 2D 중앙값 (rc 기준)
    df["mag_2D"] = median2d_on(
        df["mag_rc"].to_numpy(float),
        df["E"].to_numpy(float),
        df["N"].to_numpy(float),
        r_m=r_m, min_neighbors=min_neigh
    )

    # 4) 보정 및 레벨링
    df["corr"]      = df["mag_2D"] - df["mag_1D"]
    df["mag_level"] = df["mag_rc"] + df["corr"]  # == mag_rc - (mag_1D - mag_2D)

    return