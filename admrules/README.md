# admrules

행정규칙 수집 파이프라인 (`target=admrul`).

## 파일 구성

- `api_client.py` — `admrul` API 래퍼. `search_admrules(history=True)`로 nw=2(연혁) 검색 지원.
- `cache.py` — detail XML 캐시 (`.cache/admrule/<serial>.xml`).
- `checkpoint.py` — 페이지/detail 재개 체크포인트. 크롤 인덱스(`.cache/.admrule-index.jsonl`) 저장·로드.
- `fetch_cache.py` — 연혁 포함 전체 수집 루프. 기본 동작은 **nw=2(연혁)**.
- `converter.py` — XML → Markdown/frontmatter 변환.
- `render_spec.md` — 경로·frontmatter 렌더링 계약 (Rust 컴파일러와 공유).
- `byls_metadata.py` — 별표·별지 첨부파일 메타데이터 헬퍼.
- `validate.py` — frontmatter·바이너리 불포함 불변 검증.

## 수집 방식

### 최초 전체 수집 (연혁 포함)

```bash
cd legalize-pipeline
python -m admrules.fetch_cache --skip-quota-check --workers 40
```

기본으로 **nw=2(연혁)** 크롤을 수행하고 nw=1(현행) union을 합친 뒤, serial 기준으로 dedup한다.
크롤 인덱스(`.cache/.admrule-index.jsonl`)가 있으면 재크롤 없이 detail 수집만 재개한다.

현행본만 수집하려면:

```bash
python -m admrules.fetch_cache --skip-history --skip-quota-check
```

### 일별 증분 수집

```bash
python -m admrules.update
```

`update.py`는 발령일자 범위로 신규 발령 건만 수집한다 (연혁 backfill 불필요).

## 알려진 제한

law.go.kr nw=2 검색 인덱스에는 존재하지만 detail 조회(ID 파라미터)가 불가능한 레코드가
일부 있다. 재시도해도 API가 "필수 입력값이 존재하지 않습니다" 오류를 반환하며, 법령정보센터
측 데이터 문제로 보인다. 2026-06-16 기준 전체 138,590건 중 124건(0.09%)이 이에 해당한다.
해당 serial은 캐시되지 않으며 컴파일 대상에서 자동 제외된다.
