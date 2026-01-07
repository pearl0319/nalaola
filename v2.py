#!/usr/bin/env python
# coding: utf-8

# In[ ]:


import os
import json
import uuid
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
import shutil


# In[ ]:


# =========================
# Config
# =========================
st.set_page_config(page_title="날아올라 정산", layout="wide")

pwd = st.text_input("비밀번호", type="password")

if pwd != st.secrets["APP_PASSWORD"]:
    st.stop()
    
DATA_DIR = Path("data")
EVENTS_DIR = DATA_DIR / "events"


# =========================
# Utilities: IO
# =========================
def safe_slug(text: str) -> str:
    # 폴더/파일명용: 아주 간단히 정리
    keep = []
    for ch in text.strip():
        if ch.isalnum() or ch in ["-", "_", " "]:
            keep.append(ch)
        else:
            keep.append("_")
    return "".join(keep).strip().replace(" ", "_")[:60]


def ensure_dirs():
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)


def event_path(event_id: str) -> Path:
    return EVENTS_DIR / event_id


def load_json(path: Path, default):
    if not path.exists():
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def list_events():
    ensure_dirs()
    events = []
    if not EVENTS_DIR.exists():
        return events
    for p in sorted(EVENTS_DIR.glob("*")):
        if p.is_dir() and (p / "event.json").exists():
            meta = load_json(p / "event.json", {})
            events.append(meta)
    # 최신순 정렬(대충)
    events.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return events


def create_event(title: str, start: str, end: str):
    ensure_dirs()
    eid = f"{start}_{end}_{safe_slug(title)}"
    ep = event_path(eid)
    ep.mkdir(parents=True, exist_ok=True)
    (ep / "receipts").mkdir(parents=True, exist_ok=True)

    meta = {
        "event_id": eid,
        "title": title,
        "start": start,
        "end": end,
        "created_at": str(date.today()),
    }
    save_json(ep / "event.json", meta)

    # 멤버/지출 파일 초기화
    if not (ep / "members.json").exists():
        save_json(ep / "members.json", {
            "members": [
                {"name": "김명석", "pay_to": "카카오페이: (입력)"},
                {"name": "김민우", "pay_to": "카카오페이: (입력)"},
                {"name": "김태형", "pay_to": "카카오페이: (입력)"},
                {"name": "박영민", "pay_to": "카카오페이: (입력)"},
                {"name": "박진주", "pay_to": "카카오페이: (입력)"},
                {"name": "박천오", "pay_to": "카카오페이: (입력)"},
                {"name": "서은희", "pay_to": "카카오페이: (입력)"},
                {"name": "유인상", "pay_to": "카카오페이: (입력)"},
                {"name": "윤정원", "pay_to": "카카오페이: (입력)"},
                {"name": "윤진성", "pay_to": "카카오페이: (입력)"},
                {"name": "이대환", "pay_to": "카카오페이: (입력)"},
                {"name": "이민우", "pay_to": "카카오페이: (입력)"},
                {"name": "이선미", "pay_to": "카카오페이: (입력)"},
                {"name": "이예리", "pay_to": "카카오페이: (입력)"},
                {"name": "이종현", "pay_to": "카카오페이: (입력)"},
                {"name": "이희준", "pay_to": "카카오페이: (입력)"},
                {"name": "정원조", "pay_to": "카카오페이: (입력)"},
                {"name": "종완", "pay_to": "카카오페이: (입력)"},
                {"name": "진한", "pay_to": "카카오페이: (입력)"},
                {"name": "한윤혁", "pay_to": "카카오페이: (입력)"},
            ]
        })
    if not (ep / "expenses.json").exists():
        save_json(ep / "expenses.json", {"expenses": []})

    return eid

def delete_event(event_id: str):
    """이벤트 폴더(data/events/<event_id>)를 통째로 삭제"""
    ep = event_path(event_id)
    if ep.exists() and ep.is_dir():
        shutil.rmtree(ep)
        return True
    return False
    

# =========================
# Utilities: Data access
# =========================
def load_event(event_id: str):
    ep = event_path(event_id)
    meta = load_json(ep / "event.json", {})
    members_obj = load_json(ep / "members.json", {"members": []})
    expenses_obj = load_json(ep / "expenses.json", {"expenses": []})
    return meta, members_obj["members"], expenses_obj["expenses"]


def save_members(event_id: str, members: list):
    ep = event_path(event_id)
    save_json(ep / "members.json", {"members": members})


def save_expenses(event_id: str, expenses: list):
    ep = event_path(event_id)
    save_json(ep / "expenses.json", {"expenses": expenses})


def save_receipt_images(event_id: str, expense_id: str, files):
    """여러 장 업로드된 영수증 이미지를 event 폴더에 누적 저장"""
    ep = event_path(event_id)
    base = ep / "receipts" / expense_id
    base.mkdir(parents=True, exist_ok=True)

    saved = []
    for f in files:
        # 원본 파일명 유지하되 충돌 방지
        ext = Path(f.name).suffix.lower() or ".jpg"
        fname = f"{uuid.uuid4().hex}{ext}"
        out = base / fname
        with open(out, "wb") as w:
            w.write(f.getbuffer())
        saved.append(str(out))
    return saved


# =========================
# Settlement logic
# =========================
def build_matrix_table(expenses: list, member_names: list):
    """
    너가 올린 엑셀형:
    [결제자 | 항목 | 금액 | (멤버들...) ]
    각 지출 row에서 참여자 컬럼에 분할금액 입력
    맨 아래 TOTAL row에 멤버별 부담 합계
    """
    rows = []
    for e in expenses:
        payer = e.get("payer", "")
        item = e.get("item", "")
        amount = float(e.get("amount", 0))
        participants = e.get("participants", [])
        split_mode = e.get("split_mode", "equal")  # 현재 equal만 구현
        n = max(len(participants), 1)
        per = amount / n if split_mode == "equal" else amount / n

        row = {"결제자": payer, "항목": item, "금액": amount}
        for m in member_names:
            if m in participants:
                row[m] = per
            else:
                row[m] = ""
        rows.append(row)

    df = pd.DataFrame(rows)

    # 멤버 컬럼이 없을 수 있어서 보정
    for m in member_names:
        if m not in df.columns:
            df[m] = ""

    # TOTAL 행(멤버별 부담 합계)
    total = {"결제자": "TOTAL", "항목": "", "금액": df["금액"].sum() if len(df) else 0.0}
    for m in member_names:
        col = pd.to_numeric(df[m], errors="coerce") if len(df) else pd.Series([], dtype=float)
        total[m] = float(col.fillna(0).sum()) if len(df) else 0.0

    df_total = pd.concat([df, pd.DataFrame([total])], ignore_index=True)
    return df_total





# =========================
# UI
# =========================
ensure_dirs()

st.title("날아올라 주말 정산 (엑셀형)")

events = list_events()

with st.sidebar:
    st.header("이벤트(주말)")

    # 기존 이벤트 선택
    event_labels = ["(새로 만들기)"] + [
        f'{e.get("start","")}~{e.get("end","")} | {e.get("title","")}' for e in events
    ]
    chosen = st.selectbox("이벤트 선택", event_labels, index=0)

    if chosen == "(새로 만들기)":
        st.subheader("새 이벤트 만들기")
        title = st.text_input("이벤트 이름", value="모임")
        start = st.date_input("시작일", value=date.today())
        end = st.date_input("종료일", value=date.today())
        if st.button("이벤트 생성"):
            eid = create_event(title=title, start=str(start), end=str(end))
            st.success("생성 완료! 왼쪽 이벤트 선택에서 선택하세요.")
            st.stop()
    else:
        # chosen index -> events offset by 1
        idx = event_labels.index(chosen) - 1
        current_event = events[idx]
        event_id = current_event["event_id"]
        st.success("선택됨")
        st.caption(f'Event ID: {event_id}')

        st.divider()
        st.subheader("이벤트 삭제")

        # 실수 방지용 확인 체크
        confirm = st.checkbox("정말 이 이벤트를 삭제할게요 (되돌릴 수 없음)")

        if st.button("이벤트 삭제", type="secondary", disabled=not confirm):
            ok = delete_event(event_id)
            if ok:
                st.success("이벤트를 삭제했습니다.")
                st.rerun()
            else:
                st.error("삭제 실패: 이벤트 폴더를 찾지 못했습니다.")

if chosen == "(새로 만들기)":
    st.info("왼쪽에서 이벤트를 만들거나 선택하세요.")
    st.stop()

# Load current event
meta, members, expenses = load_event(event_id)
member_names = [m["name"] for m in members]

tabs = st.tabs(["➕ 지출(영수증) 추가", "📊 정산표", "👥 멤버/계좌 관리", "🧾 영수증 보기"])

# -------------------------
# Tab: Add expense
# -------------------------
with tabs[0]:
    st.subheader("지출(영수증) 추가")
    left, right = st.columns([1, 1])

    with left:
        payer = st.selectbox("결제자", member_names + ["(게스트 결제자 추가)"])
        guest_payer = ""
        if payer == "(게스트 결제자 추가)":
            guest_payer = st.text_input("게스트 결제자 이름")
        item = st.text_input("항목(예: 치킨, 술, 택시 등)")
        amount = st.number_input("금액", min_value=0, step=1000)
        participants = st.multiselect("참여자(나눌 사람들)", member_names, default=member_names)
        note = st.text_input("메모(선택)")
        split_mode = st.selectbox("분할 방식", ["equal"], index=0, help="현재는 1/N 균등분할만 지원")

    with right:
        imgs = st.file_uploader("영수증 사진 업로드(여러장 가능)", type=["png", "jpg", "jpeg", "heic"], accept_multiple_files=True)
        if imgs:
            st.caption(f"업로드된 파일: {len(imgs)}장")
            # 구버전 streamlit 호환 위해 use_container_width 사용 안 함
            for i, f in enumerate(imgs[:3], start=1):
                st.image(f, caption=f"미리보기 {i}", width=500)
            if len(imgs) > 3:
                st.caption("미리보기는 최대 3장만 표시합니다.")

    if st.button("저장", type="primary"):
        if payer == "(게스트 결제자 추가)":
            payer_final = guest_payer.strip()
        else:
            payer_final = payer

        if not payer_final:
            st.error("결제자를 입력하세요.")
            st.stop()
        if not item.strip():
            st.error("항목을 입력하세요.")
            st.stop()
        if amount <= 0:
            st.error("금액을 입력하세요.")
            st.stop()
        if len(participants) == 0:
            st.error("참여자를 1명 이상 선택하세요.")
            st.stop()

        expense_id = f"{len(expenses)+1:04d}_{safe_slug(item)}_{int(amount)}"
        saved_paths = []
        if imgs:
            saved_paths = save_receipt_images(event_id, expense_id, imgs)

        new_exp = {
            "expense_id": expense_id,
            "payer": payer_final,
            "item": item.strip(),
            "amount": float(amount),
            "participants": participants,
            "split_mode": split_mode,
            "note": note.strip(),
            "receipt_paths": saved_paths,  # 여러 장 누적 저장
            "created_at": str(date.today()),
        }
        expenses.append(new_exp)
        save_expenses(event_id, expenses)
        st.success("저장 완료! (정산표 탭에서 확인)")
        st.rerun()

# -------------------------
# Tab: Matrix table
# -------------------------
with tabs[1]:
    st.subheader("정산표 (엑셀형)")
    st.caption("형태: 결제자/항목/금액 + 참여자별 분할금액 + 마지막 TOTAL")

    df_matrix = build_matrix_table(expenses, member_names)

    # 보기 좋게 포맷(금액)
    def fmt_money(x):
        try:
            if x == "" or pd.isna(x):
                return ""
            return f"{float(x):,.0f}"
        except Exception:
            return x

    df_show = df_matrix.copy()
    money_cols = ["금액"] + member_names
    for c in money_cols:
        if c in df_show.columns:
            df_show[c] = df_show[c].apply(fmt_money)

    st.dataframe(df_show, use_container_width=True, height=520)

    # CSV 다운로드
    csv = df_matrix.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "정산표 CSV 다운로드",
        data=csv,
        file_name=f'{meta.get("start","")}_{meta.get("end","")}_settlement.csv',
        mime="text/csv",
    )

    # 지출 목록 간단 관리(삭제)
    st.divider()
    st.subheader("지출 삭제(선택)")
    if len(expenses) == 0:
        st.info("삭제할 지출이 없습니다.")
    else:
        options = [f'{e["expense_id"]} | {e["payer"]} | {e["item"]} | {int(e["amount"]):,}원' for e in expenses]
        sel = st.selectbox("삭제할 지출 선택", ["(선택 안 함)"] + options)
        if sel != "(선택 안 함)":
            if st.button("선택한 지출 삭제", type="secondary"):
                idx = options.index(sel)
                exp = expenses.pop(idx)
                save_expenses(event_id, expenses)
                st.success(f"삭제 완료: {exp['expense_id']}")
                st.rerun()


# -------------------------
# Tab: Members management
# -------------------------
with tabs[2]:
    st.subheader("멤버/계좌(카카오페이) 관리")

    st.write("멤버 추가/삭제, 그리고 각 멤버의 계좌번호/카카오페이 정보를 저장합니다.")
    dfm = pd.DataFrame(members)

    edited = st.data_editor(
        dfm,
        use_container_width=True,
        num_rows="dynamic",
        column_config={
            "name": st.column_config.TextColumn("name", required=True),
            "pay_to": st.column_config.TextColumn("pay_to", help="예: 카카오페이: 김민우 / 국민 123-45-67890"),
        },
        key="members_editor",
    )

    if st.button("멤버 저장", type="primary"):
        edited = edited.fillna("")

        cleaned = []
        for _, r in edited.iterrows():
            name = str(r.get("name", "")).strip()
            if not name:
                continue
            cleaned.append({
                "name": name,
                "pay_to": str(r.get("pay_to", "")).strip()
            })

        save_members(event_id, cleaned)
        st.success("저장 완료!")
        st.rerun()

# -------------------------
# Tab: Receipts gallery
# -------------------------
with tabs[3]:
    st.subheader("영수증 보기 (누적)")

    if len(expenses) == 0:
        st.info("등록된 지출이 없습니다.")
        st.stop()

    # 지출 선택(전체 보기 포함)
    options = ["(전체 보기)"] + [
        f'{e["expense_id"]} | {e["payer"]} | {e["item"]} | {int(e["amount"]):,}원'
        for e in expenses
    ]
    sel = st.selectbox("지출 선택", options, index=0)

    show_list = expenses
    if sel != "(전체 보기)":
        idx = options.index(sel) - 1
        show_list = [expenses[idx]]

    # 카드처럼 출력
    for e in show_list:
        st.markdown(f"### {e['payer']} · {e['item']} · {int(e['amount']):,}원")
        st.caption(f"expense_id: {e['expense_id']}  |  날짜: {e.get('created_at','')}")
        if e.get("note"):
            st.write(f"메모: {e['note']}")

        paths = e.get("receipt_paths", [])
        if not paths:
            st.info("영수증이 없습니다.")
            st.divider()
            continue

        # 이미지들을 누적 표시(그리드)
        cols = st.columns(3)
        for i, p in enumerate(paths):
            path = Path(p)
            if path.exists():
                with cols[i % 3]:
                    st.image(str(path), caption=path.name, use_container_width=True)
            else:
                st.warning(f"파일이 없어요: {p}")

        st.divider()

# In[ ]:




