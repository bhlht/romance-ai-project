# DeepSeek 7B QLoRA 학습 가이드

이 가이드는 수집한 로맨스 소설 데이터를 사용하여 DeepSeek 7B 모델을 미세 조정(Fine-tune)하는 방법을 단계별로 설명합니다.

## 옵션 1: Google Colab 사용 (권장)

미세 조정에는 약 16GB 이상의 GPU VRAM이 필요하므로, **Google Colab Pro** (A100 또는 V100 GPU 사용)를 사용하는 것이 가장 간편하고 확실합니다.

### 1단계: 파일 준비
학습을 위해 다음 두 가지 파일이 필요합니다.
1.  **데이터 파일**: `combined_romance_data.txt` (전처리 스크립트를 실행하여 생성된 파일)
2.  **학습 스크립트**: `scripts/train_model.py` (프로젝트에 포함된 파이썬 파일)

### 2단계: Google Drive 업로드
1.  Google Drive에 접속하여 적당한 폴더(예: `romance_ai`)를 만듭니다.
2.  위에서 준비한 `combined_romance_data.txt`와 `train_model.py` 두 파일을 해당 폴더에 업로드합니다.

### 3단계: Colab 노트북 열기
1.  [Google Colab](https://colab.research.google.com/)에 접속하여 **새 노트**를 만듭니다.
2.  상단 메뉴에서 **런타임 > 런타임 유형 변경**을 클릭합니다.
3.  **하드웨어 가속기**: **GPU** 선택
4.  **GPU 클래스**: **A100** (가장 빠름) 또는 **V100** 선택 (Pro 구독자 전용)
5.  **고용량 RAM**: 체크 (가능하다면)

> **팁**: A100을 선택하면 학습 속도가 T4(무료)보다 훨씬 빠르며, 스크립트가 자동으로 최적화(bf16)해줍니다.

### 4단계: 학습 코드 실행
아래의 코드 셀들을 순서대로 Colab 노트북에 복사하여 실행하세요.

**셀 1: 구글 드라이브 연결 (마운트)**
```python
from google.colab import drive
drive.mount('/content/drive')
%cd /content/drive/MyDrive/romance_ai
!ls  # 여기에 train_model.py 파일이 보이는지 확인하세요.
```

**만약 `[Errno 2] No such file or directory` 에러가 난다면?**
구글 드라이브에 `romance_ai` 폴더가 없거나 이름이 다른 것입니다. 폴더명을 확인하고 `%cd` 경로를 수정하세요.

**셀 2: 필수 프로그램 설치**
```python
!pip install -q -U --no-cache-dir torch torchvision torchaudio transformers peft bitsandbytes trl accelerate datasets scipy
```

**셀 3: 학습 스크립트 실행**
```python
!python train_model.py --data_path combined_romance_data.txt --output_dir deepseek_finetuned_model
```
*(주의: 파일명이 다르거나 경로가 다르다면 명령어를 그에 맞게 수정해야 합니다)*

### 5단계: 결과물 다운로드
학습이 성공적으로 끝나면, 구글 드라이브의 같은 폴더에 `deepseek_finetuned_model`이라는 폴더가 새로 생깁니다.
1. 이 폴더를 내 컴퓨터(로컬)로 다운로드합니다.
2. 프로젝트 폴더 내 `d:/myProject/python/streamlit/deepseek_finetuned_model` 위치에 덮어씌웁니다.

---

## 옵션 2: GCP GPU 인스턴스 사용

만약 이미 고성능 GCP 인스턴스(L4, A100 등)를 빌렸다면, 거기서 직접 학습할 수도 있습니다.

1.  **접속**: SSH를 통해 인스턴스에 접속합니다.
2.  **이동**: 프로젝트 폴더로 이동합니다.
3.  **설치**: 필요한 패키지를 설치합니다.
    ```bash
    pip install torch transformers peft bitsandbytes trl accelerate datasets scipy
    ```
4.  **실행**: 스크립트를 실행합니다.
    ```bash
    python scripts/train_model.py
    ```

## 학습 후 할 일

`deepseek_finetuned_model` 폴더가 준비되었다면:

1.  **FastAPI 백엔드 재시작**:
    기존에 켜진 터미널에서 `Ctrl+C`로 끄고 다시 켭니다.
    ```bash
    python -m uvicorn backend.main:app --reload
    ```
2.  **모드 변경**:
    `.env` 파일에서 `MOCK_MODE=False`로 설정해야 "진짜 AI"가 동작합니다.
