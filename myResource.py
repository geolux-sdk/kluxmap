import os
from pathlib import Path

import pandas as pd
from loguru import logger

from mySettings import config


def resource_path(name: str) -> str:
    IMAGE_PATH = "./img/"

    base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, IMAGE_PATH, name)


def load_SEC_file(file_path: str, out_folder: str = None) -> str | None:
    """
    IAGA-2002 SEC 파일을 읽어서 필요한 컬럼만 추출 후 CSV로 저장합니다.

    Parameters
    ----------
    file_path : str
        입력 SEC 파일 경로
    out_folder : str, optional
        결과 CSV를 저장할 폴더 (기본: 프로젝트의 'Diurnal Data Folder')

    Returns
    -------
    str | None
        저장된 CSV 파일 경로. 실패 시 None.
    """
    try:
        # SEC 파일 읽기
        df = pd.read_csv(
            file_path,
            sep=r"\s+",  # 공백 구분
            comment="#",  # 주석 무시
            skiprows=21,  # 헤더 스킵
        )

        # 컬럼 선택 + 이름 변경
        if "CKIF" in df.columns:
            df = df[["DATE", "TIME", "CKIF"]].rename(
                columns={"DATE": "Date", "TIME": "Time", "CKIF": "Mag"}
            )
        elif "CYGF" in df.columns:
            df = df[["DATE", "TIME", "CYGF"]].rename(
                columns={"DATE": "Date", "TIME": "Time", "CYGF": "Mag"}
            )
        else:
            logger.error(f"SEC file {file_path}에 CKIF 또는 CYGF 컬럼이 없음")
            return None

        # 폴더가 없으면 에러 처리
        if not os.path.exists(out_folder):
            logger.error(f"Output folder does not exist: {out_folder}")
            return None

        # 파일명 변환
        file_name = os.path.splitext(os.path.basename(file_path))[0] + ".csv"
        out_file_path = os.path.join(out_folder, file_name)

        # CSV 저장
        df.to_csv(out_file_path, index=False)
        logger.info(f"SEC file 변환 완료 → {out_file_path}")
        return out_file_path

    except Exception as e:
        logger.error(f"SEC 파일 변환 실패 ({file_path}): {e}")
        return None


def make_project_subfolder(subfolder_name: str) -> Path | None:
    """
    프로젝트 경로 내 지정된 하위 폴더를 확인합니다.
    폴더가 없으면 생성하지 않고 에러 로그를 남기고 None을 반환합니다.

    Parameters
    ----------
    subfolder_name : str
        확인할 하위 폴더 이름 (예: "Diurnal Data Folder")

    Returns
    -------
    str | None
        하위 폴더의 경로 (존재할 경우), 없으면 None
    """
    project_path = config.get("project_path", "")
    if not project_path:
        logger.error("Project path is not set in config.")
        return None

    subfolder_path = Path(project_path) / subfolder_name

    try:
        subfolder_path.mkdir(exist_ok=True)
        logger.debug(f"Subfolder ensured: {subfolder_path}")
        return subfolder_path
    except Exception as e:
        logger.error(f"Failed to create subfolder {subfolder_path}: {e}")
        return None
