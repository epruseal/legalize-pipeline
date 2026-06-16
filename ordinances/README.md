# ordinances

자치법규 수집 파이프라인 (`target=ordin`).

## 파일 구성

- `api_client.py` — `ordin` API 래퍼. `search_ordinances(nw=...)` 로 현행/연혁 검색 지원.
- `cache.py` — detail XML 캐시 (`.cache/ordinance/<MST>.xml`).
- `checkpoint.py` — 크롤 인덱스(`.cache/.ordinance-index.jsonl`) 저장·로드.
- `fetch_cache.py` — 연혁 포함 전체 수집 루프. 기본 동작은 **nw=2(연혁)**.
- `failures.py` — 조회 실패 레코드 JSONL 기록 (`.cache/ordinance_failures.jsonl`).
- `converter.py` — XML → Markdown/frontmatter 변환.
- `byls_metadata.py` — 별표·별지 첨부파일 메타데이터 헬퍼.
- `validate.py` — frontmatter·바이너리 불포함 불변 검증.

## 수집 방식

### 최초 전체 수집 (연혁 포함)

```bash
cd legalize-pipeline
LAW_OC=<api_key> python -m ordinances.fetch_cache --skip-quota-check --workers 40
```

기본으로 **nw=2(연혁)** 크롤을 수행하고 nw=1(현행) union을 합친 뒤, MST(`자치법규일련번호`) 기준으로
dedup한다. 크롤 인덱스(`.cache/.ordinance-index.jsonl`)가 있으면 재크롤 없이 detail 수집만 재개한다.

현행본만 수집하려면:

```bash
LAW_OC=<api_key> python -m ordinances.fetch_cache --skip-history --skip-quota-check
```

### 일별 증분 수집

```bash
LAW_OC=<api_key> python -m ordinances.update
```

`update.py`는 공포일자 범위로 신규 공포 건만 수집한다 (연혁 backfill 불필요).

## 알려진 제한

law.go.kr nw=2 검색 인덱스에 존재하지만 detail 조회가 불가능한 레코드가 일부 있다.

- **404** — 법령정보센터에서 삭제된 레코드. 재시도해도 복구 불가.
- **500** — 서버 일시 오류. 재시도 시 일부 복구 가능.

2026-06-16 기준 전체 864,510건 중 165건(0.02%)이 이에 해당한다. 해당 MST는 캐시되지 않으며
컴파일 대상에서 자동 제외된다. 일시 오류(500) 건은 다음 수집 시 재시도하면 해소될 수 있다.
