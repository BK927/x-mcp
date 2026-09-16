# X Research MCP

[English](README.md) · [설계·인터페이스](docs/design.md) · [검증 결과](docs/verification.md)

공개 X 자료를 조사하는 읽기 전용 MCP 서버입니다. **8개 도구**, 무료 FxTwitter
API 우선 접근, 필요한 경우의 로그인 세션 보완, 작은 응답과 이어 읽기를 제공합니다.
유료 API나 서버 자체 LLM은 호출하지 않습니다.

게시물·스레드·답글·계정·검색·관계·공개 컬렉션·트렌드 조회와 저장한 게시물의 집계를
지원합니다. 게시, 좋아요, 팔로우 변경, DM, 북마크, 개인 홈 피드, 알림, 보호 계정
접근은 제공하지 않습니다.

## 현재 검증 상태

0.1.0 소스 설치 버전입니다. PyPI 배포를 의미하지 않습니다.
2026-09-16 공개 게시물·프로필·사용자 게시물·스레드·답글·트렌드 호출은 성공했습니다.
무료 게시물 검색은 `404`와 빈 목록을 반환해 **결과 없음이 아닌 공급자 장애**로 처리했습니다.
무료 사용자 검색은 자동완성 후보 조회 방식으로 응답했습니다.
세션 어댑터는 모의 응답으로 검증했으며 실제 사용자 계정으로는 아직 검증하지 않았습니다.
리스트·커뮤니티는 원본에서 공개 여부를 명확히 확인할 수 있을 때만 반환합니다.

## 설치

Python 3.12 이상과 uv가 필요합니다.

```sh
git clone https://github.com/BK927/x-mcp.git
cd x-mcp
uv sync --frozen --no-dev
uv run --frozen --no-dev x-mcp serve
```

일반 MCP 클라이언트 설정 예시입니다. 경로는 본인의 절대 경로로 바꾸세요.

```json
{
  "mcpServers": {
    "x-research": {
      "command": "uv",
      "args": ["run", "--frozen", "--no-dev", "--directory", "C:/Users/you/repo/x-mcp", "x-mcp", "serve"]
    }
  }
}
```

로그인 없이 무료 공개 API 기능부터 사용할 수 있습니다. 패키지 이름은
`bk927-x-mcp`, 실행 명령은 `x-mcp`입니다. 다른 프로젝트의 `pip install x-mcp`와
혼동하지 마세요. 재현 가능한 설치에는 검토한 커밋을 사용하세요.

## 도구

| 도구 | 용도 |
|---|---|
| `x_search` | 게시물·사용자 검색 |
| `x_post_get` | 게시물·작성자 스레드·답글·인용·리포스트한 사용자 |
| `x_user_get` | 프로필·게시물·답글 포함 목록·미디어·아티클·팔로워·팔로잉 |
| `x_collection_get` | 공개 확인이 가능한 리스트·커뮤니티 조회 |
| `x_trends_get` | 공급자가 제공하는 트렌드와 맥락 |
| `x_analyze` | 저장된 게시물의 활동·반응·링크 도메인·해시태그 집계 |
| `x_result_get` | 저장 결과 또는 생략된 본문·JSON 이어 읽기 |
| `x_status` | 기능별 설정·검증 상태와 도구 사용 규칙 |

검색·답글은 전체 데이터가 아닌 표본입니다. 한국어로 요청했다고 한국 지역 트렌드로
간주하지 않습니다. 없는 반응 수치는 0으로 바꾸지 않습니다.

## 로그인 연결: 두 방식 지원

쿠키 파일을 준비한 경우 JSON 또는 Netscape 형식을 가져올 수 있습니다.

```sh
uv sync --frozen --no-dev --extra session
uv run --frozen --no-dev --extra session x-mcp auth import --file /private/path/export.json
```

서버 실행과 MCP 설정의 `uv run` 인자에도 `--extra session`을 유지하세요.
쿠키 값은 채팅이나 MCP 도구에 넣지 않습니다. 저장소에는 필요한 `auth_token`, `ct0`만
남기며 기존 브라우저 전체 프로필이나 비밀번호는 가져오지 않습니다.

전용 창에서 직접 로그인하려면 다음을 실행합니다.

```sh
uv sync --frozen --no-dev --extra session --extra browser
uv run --frozen --no-dev --extra session --extra browser playwright install chromium
uv run --frozen --no-dev --extra session --extra browser x-mcp auth login
```

브라우저에서 로그인한 뒤 터미널에서 Enter를 누르면 같은 세션 저장소에 저장됩니다.
브라우저는 그때만 필요합니다. 개인 서버에는 로컬에서 준비한 세션 파일을 마운트할 수
있습니다. 세션이 만료되면 다시 연결해야 하며 자동 계정 교체는 하지 않습니다.

`x-mcp doctor`는 설정과 기록된 상태만 보여줍니다. `doctor --live`는 공개 게시물,
프로필, 검색을 실제로 조회하므로 명시적으로 실행할 때만 사용합니다.

## 토큰과 이어 읽기

목록 기본 10개·최대 50개, compact 기본 응답 12KiB입니다. 긴 본문은 600자까지만
보여주고 생략 여부를 표시합니다. 전체 본문은 `x_result_get`의 `item_id`로,
정규화된 전체 객체는 `field=json`으로 복구할 수 있습니다.

조회 응답의 `page.next_cursor`는 원래 도구에 같은 검색 조건과 함께 전달합니다.
서버는 이미 받은 나머지 항목을 먼저 반환하고 그다음 상위 페이지를 요청합니다.
`x_result_get`은 네트워크를 호출하지 않으며 `page.source_cursor`가 나오면 원래
조회 도구로 돌아가 사용합니다. 저장 결과는 기본 1시간 유지됩니다.

`x_analyze`는 이미 저장한 게시물만 계산합니다. 읽지 않은 페이지를 자동 수집하거나
LLM으로 감성 분석·번역·요약하지 않습니다.

고정된 한·영·일 목록 예제의 명세 크기와 절감률은 [검증 문서](docs/verification.md)에
기록합니다. MCP 호환성을 위해 JSON 텍스트와 구조화 응답을 함께 제공하므로 실제
클라이언트가 둘 다 문맥에 넣는 경우의 토큰도 따로 측정합니다.

## 개인 서버

```sh
uv run --frozen --no-dev --extra session x-mcp serve --transport http
```

기본 주소는 `http://127.0.0.1:8766/mcp`입니다. 로컬 주소를 포함한 모든 HTTP 실행에는
32자 이상의 무작위 `MCP_ACCESS_TOKEN`이 필요합니다. 외부 접속에는 HTTPS 프록시를 사용하고 실제 HTTPS origin을
`PUBLIC_BASE_URL`로 지정합니다. Docker 및 상태 볼륨 구성은
[배포 문서](docs/deployment.md)를 참고하세요.

공개 소스·개인용 단일 서버를 대상으로 합니다. 다중 사용자 SaaS, 웹 ChatGPT 전용
OAuth, Cloud Run 전용 구성, 상시 수집은 첫 버전에 포함하지 않습니다.

**X 쿠키는 읽기 전용 권한의 API 키가 아닙니다.** 현재 세션 파일과 계정 DB는 파일
접근 권한으로 보호되며 애플리케이션 암호화는 없습니다. 서버가 침해되면 쿠키가 노출될
수 있습니다. 주 계정 쿠키를 여러 클라우드 워커에 복제하기보다 신뢰하는 한 호스트에
보관하는 구성을 권장합니다. [자격 증명 보안 설계](docs/security-model.md)를 참고하세요.

무료 API 운영과 X 내부 구현은 바뀔 수 있습니다. 이 프로젝트는 X와 관계없는
비공식 MIT 프로젝트이며, 무료는 유료 데이터 API를 호출하지 않는다는 뜻입니다.
