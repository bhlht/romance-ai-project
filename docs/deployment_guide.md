# GCP 배포 및 파일 전송 가이드

이 문서는 학습된 모델과 백엔드 코드를 Google Cloud Platform (GCP) 서버로 전송하고 실행하는 방법을 상세히 설명합니다.

## 전제 조건
- GCP 인스턴스(GPU 서버)가 생성되어 있어야 합니다.
- 로컬 컴퓨터에 `google-cloud-sdk` (gcloud cli)가 설치되어 있어야 합니다.
- 학습된 `deepseek_finetuned_model` 폴더가 있어야 합니다.

---

## 0단계: Google Cloud SDK (gcloud CLI) 설치

GCP 서버를 제어하려면 내 컴퓨터에 도구가 필요합니다.

1.  **다운로드**: [Google Cloud SDK 설치 페이지](https://cloud.google.com/sdk/docs/install?hl=ko)에서 Windows용 설치파일을 다운로드합니다.
2.  **설치**: 다운로드한 파일을 실행하여 설치를 진행합니다. (기본 설정대로 '다음'만 누르시면 됩니다.)
3.  **초기 설정**:
    설치가 끝나면 터미널(PowerShell)을 열고 다음 명령어를 입력합니다.
    ```powershell
    gcloud init
    ```
    - 구글 계정으로 로그인 창이 뜨면 로그인합니다.
    - 사용할 프로젝트(`romance-ai-creator` 등)를 선택합니다.

---

## 1단계: 파일 준비 (로컬에서)

전송해야 할 것은 크게 두 가지입니다.
1. **code 폴더**: `backend` 폴더
2. **model 폴더**: `deepseek_finetuned_model` (학습 완료 후 생성된 것)

**주의**: `deepseek_finetuned_model`은 용량이 큽니다. Colab에서 학습했다면, 먼저 로컬 컴퓨터로 다운로드해야 합니다.

---

## 2단계: 파일 전송하기 (Upload)

초보자에게 가장 쉬운 두 가지 방법을 소개합니다.

### 방법 A: 터미널 명령어 (gcloud command) - 추천
윈도우 터미널(PowerShell)을 열고, 프로젝트 폴더(`d:\myProject\python\streamlit`)에서 다음 명령어를 입력합니다.

**1. 백엔드 코드 전송**
```powershell
gcloud compute scp --recurse backend romance-ai-gpu:~/ --zone=us-central1-a
```

**2. 모델 폴더 전송 (시간이 좀 걸립니다)**
```powershell
gcloud compute scp --recurse deepseek_finetuned_model romance-ai-gpu:~/ --zone=us-central1-a
```
*(참고: `romance-ai-gpu`는 만든 인스턴스 이름입니다. 다르면 수정해주세요.)*

---

### 방법 B: FileZilla (화면으로 보고 옮기기)
명령어가 어렵다면 FTP 프로그램인 FileZilla를 사용할 수 있습니다.

1. **GCP SSH 키 생성**:
   터미널에서 `gcloud compute ssh romance-ai-gpu --zone=us-central1-a`를 한 번 실행하면 키가 자동 생성됩니다.
2. **FileZilla 설정**:
   - **호스트**: `sftp://[GCP_외부_IP]` (인스턴스 IP)
   - **사용자**: 구글 계정 아이디 (또는 ssh 키 사용자명)
   - **키 파일**: `C:\Users\OXFORD\.ssh\google_compute_engine` (PPK 파일이 필요할 수 있습니다. PuTTYgen으로 변환 필요)
   
*FileZilla 설정이 복잡할 수 있으므로, 가능하면 방법 A를 추천합니다.*

---

## 3단계: GCP 서버 접속 및 실행

파일 전송이 끝났다면, 이제 GCP 서버 안으로 들어가서 서버를 켭니다.

**1. 서버 접속**
```powershell
gcloud compute ssh romance-ai-gpu --zone=us-central1-a
```

**2. 환경 설정 (서버 안에서)**
서버에 처음 들어갔다면 필수 패키지를 설치해야 합니다.
```bash
# 미니콘다(Python) 설치 (없는 경우)
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh

# 패키지 설치
pip install fastapi uvicorn torch transformers peft bitsandbytes accelerate google-generativeai python-dotenv
```

**3. 백엔드 실행**
```bash
# 백엔드 폴더 확인
ls -l

# 실행 (MOCK_MODE=False로 진짜 AI 가동)
export MOCK_MODE=False
export GEMINI_API_KEY="당신의_키_입력"
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

---

## 4단계: 로컬 프론트엔드 연결

GCP 서버가 켜져 있는 상태에서 내 컴퓨터의 설정을 바꿉니다.

1. 내 컴퓨터의 `.env` 파일 열기.
2. `BACKEND_URL` 수정:
   ```ini
   BACKEND_URL=http://[GCP_외부_IP]:8000
   ```
3. 프론트엔드 실행:
   ```powershell
   streamlit run frontend/app.py
   ```

이제 내 컴퓨터에서 버튼을 누르면 GCP 슈퍼컴퓨터가 소설을 써줍니다!
