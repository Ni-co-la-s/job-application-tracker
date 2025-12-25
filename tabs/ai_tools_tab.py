"""AI Tools tab for job analysis and chat."""

import json
import logging
from typing import Any

import streamlit as st

from constants import PRESETS_FILE
from modules.database import JobDatabase
from modules.llm_config import get_config_manager

logger = logging.getLogger(__name__)


def render_ai_tools(db: JobDatabase, jobs: list[dict[str, Any]]) -> None:
    """Render the AI Tools tab.

    Args:
        db: Database instance.
        jobs: List of job dictionaries.
    """

    st.title("🤖 AI Tools")

    # Initialize session state for presets
    if "presets" not in st.session_state:
        try:
            with open(PRESETS_FILE, "r", encoding="utf-8") as f:
                st.session_state.presets = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            st.session_state.presets = {}

    # Initialize session state for job chat
    if "job_chat_history" not in st.session_state:
        st.session_state.job_chat_history = {}
    if "selected_job_for_chat" not in st.session_state:
        st.session_state.selected_job_for_chat = None
    if "selected_preset" not in st.session_state:
        st.session_state.selected_preset = None

    # ==================== JOB SELECTION ====================
    if not jobs:
        st.warning(
            "📭 No jobs found. Please add some jobs first using the Job Browser tab."
        )
        return

    # Job selector at the top
    job_options = {
        f"{j['title']} @ {j['company']} (Score: {j['llm_score'] or 0}/10)": j
        for j in jobs
    }
    selected_job_label = st.selectbox(
        "💼 Select a job to chat about",
        options=list(job_options.keys()),
        key="job_chat_select",
    )
    selected_job = job_options[selected_job_label]

    # When a new job is selected, reset the chat history for that job if not exists
    if st.session_state.selected_job_for_chat != selected_job["id"]:
        st.session_state.selected_job_for_chat = selected_job["id"]
        if selected_job["id"] not in st.session_state.job_chat_history:
            st.session_state.job_chat_history[selected_job["id"]] = []

    chat_history = st.session_state.job_chat_history[selected_job["id"]]

    # ==================== MAIN LAYOUT: SIDEBAR + CHAT ====================
    col_sidebar, col_chat = st.columns([1, 2])

    # ==================== LEFT SIDEBAR: JOB INFO & PRESETS ====================
    with col_sidebar:
        # Job info card
        with st.container():
            st.markdown("### 📋 Job Details")
            st.markdown(f"**{selected_job['title']}**")
            st.caption(f"🏢 {selected_job['company']} • 📍 {selected_job['location']}")
            st.caption(f"⭐ Score: {selected_job['llm_score'] or 0}/10")

            # Show description preview (expanded by default)
            with st.expander("📄 Job Description", expanded=True):
                description = selected_job["description"] or "No description available"
                # Show first 600 characters with scroll
                st.markdown(description, unsafe_allow_html=True)

        st.divider()

        # Chat controls
        st.markdown("### 🎛️ Controls")
        col_reset, col_messages = st.columns(2)
        with col_reset:
            if st.button("🔄 Reset", width="stretch", key="reset_chat"):
                st.session_state.job_chat_history[selected_job["id"]] = []
                st.session_state.selected_preset = None
                st.rerun()
        with col_messages:
            st.metric("Messages", len(chat_history), label_visibility="collapsed")

        st.divider()

        # Preset quick actions
        st.markdown("### 🎯 Quick Prompts")

        if st.session_state.presets:
            for preset_name, preset in st.session_state.presets.items():
                # Create a button for each preset
                button_label = f"📌 {preset_name}"
                if st.button(
                    button_label, key=f"preset_quick_{preset_name}", width="stretch"
                ):
                    # Fill template
                    filled_prompt = preset["user_prompt"].format(
                        title=selected_job["title"],
                        company=selected_job["company"],
                        location=selected_job["location"],
                        description=selected_job["description"][:500] + "..."
                        if len(selected_job["description"]) > 500
                        else selected_job["description"],
                    )

                    # Add to chat
                    chat_history.append({"role": "user", "content": filled_prompt})
                    st.session_state.selected_preset = preset

                    # Get AI response
                    with st.spinner("Thinking..."):
                        context = f"""
                        Job Title: {selected_job["title"]}
                        Company: {selected_job["company"]}
                        Location: {selected_job["location"]}
                        Job Description: {selected_job["description"]}
                        """

                        system_message = f"You are a helpful assistant that answers questions about this job. Here is the job information:\n{context}"
                        if preset.get("system_prompt"):
                            system_message = preset["system_prompt"] + "\n\n" + context

                        config_manager = get_config_manager()
                        client = config_manager.get_client_for_stage("chat")

                        if client:
                            messages = [{"role": "system", "content": system_message}]
                            for msg in chat_history:
                                if msg["role"] in ("user", "assistant"):
                                    messages.append(msg)
                            try:
                                response = client.chat.completions.create(
                                    model=config_manager.get_config_for_stage(
                                        "chat"
                                    ).model,
                                    messages=messages,
                                    temperature=0.7,
                                    max_tokens=500,
                                )
                                reply = response.choices[0].message.content
                            except Exception as e:
                                reply = f"❌ Error: {str(e)}"
                        else:
                            reply = "❌ Chat LLM is not configured. Please check your .env file."

                        chat_history.append({"role": "assistant", "content": reply})

                    st.session_state.job_chat_history[selected_job["id"]] = chat_history
                    st.rerun()
        else:
            st.info("💡 Create presets below to get quick prompts here")

        st.divider()

        # Preset management (collapsed by default)
        with st.expander("⚙️ Manage Presets"):
            preset_action = st.radio(
                "Action", ["Create New", "Edit/Delete"], horizontal=True
            )

            if preset_action == "Create New":
                with st.form("create_preset_form", clear_on_submit=True):
                    new_name = st.text_input(
                        "Preset Name", placeholder="e.g., Salary Research"
                    )
                    new_system = st.text_area(
                        "System Prompt (optional)",
                        placeholder="You are a career advisor...",
                    )
                    new_user = st.text_area(
                        "User Prompt Template",
                        placeholder="Use {title}, {company}, {location}, {description}",
                        help="Example: Research typical salary for {title} at {company}",
                    )

                    if st.form_submit_button("Create Preset", width="stretch"):
                        if new_name and new_user:
                            if new_name in st.session_state.presets:
                                st.error(f"Preset '{new_name}' already exists")
                            else:
                                st.session_state.presets[new_name] = {
                                    "name": new_name,
                                    "system_prompt": new_system,
                                    "user_prompt": new_user,
                                }
                                with open(PRESETS_FILE, "w", encoding="utf-8") as f:
                                    json.dump(st.session_state.presets, f, indent=2)
                                st.toast(f"✓ Created '{new_name}'")
                                st.rerun()
                        else:
                            st.error("Name and User Prompt are required")

            else:  # Edit/Delete
                if st.session_state.presets:
                    preset_to_edit = st.selectbox(
                        "Select preset",
                        options=list(st.session_state.presets.keys()),
                        key="preset_to_edit",
                    )

                    if preset_to_edit:
                        preset = st.session_state.presets[preset_to_edit]

                        with st.form("edit_preset_form"):
                            edit_name = st.text_input("Name", value=preset["name"])
                            edit_system = st.text_area(
                                "System Prompt", value=preset.get("system_prompt", "")
                            )
                            edit_user = st.text_area(
                                "User Prompt", value=preset["user_prompt"]
                            )

                            col1, col2 = st.columns(2)
                            with col1:
                                if st.form_submit_button("💾 Update", width="stretch"):
                                    if edit_name != preset_to_edit:
                                        if edit_name in st.session_state.presets:
                                            st.error(f"'{edit_name}' already exists")
                                        else:
                                            del st.session_state.presets[preset_to_edit]
                                            st.session_state.presets[edit_name] = {
                                                "name": edit_name,
                                                "system_prompt": edit_system,
                                                "user_prompt": edit_user,
                                            }
                                            with open(
                                                PRESETS_FILE, "w", encoding="utf-8"
                                            ) as f:
                                                json.dump(
                                                    st.session_state.presets,
                                                    f,
                                                    indent=2,
                                                )
                                            st.toast("✓ Updated")
                                            st.rerun()
                                    else:
                                        st.session_state.presets[edit_name] = {
                                            "name": edit_name,
                                            "system_prompt": edit_system,
                                            "user_prompt": edit_user,
                                        }
                                        with open(
                                            PRESETS_FILE, "w", encoding="utf-8"
                                        ) as f:
                                            json.dump(
                                                st.session_state.presets, f, indent=2
                                            )
                                        st.toast("✓ Updated")
                                        st.rerun()

                            with col2:
                                if st.form_submit_button("🗑️ Delete", width="stretch"):
                                    del st.session_state.presets[preset_to_edit]
                                    with open(PRESETS_FILE, "w", encoding="utf-8") as f:
                                        json.dump(st.session_state.presets, f, indent=2)
                                    st.toast("✓ Deleted")
                                    st.rerun()
                else:
                    st.info("No presets yet. Create one above!")

    # ==================== RIGHT SIDE: CHAT INTERFACE ====================
    with col_chat:
        st.markdown("### 💬 Chat")

        # Chat container with fixed height
        chat_container = st.container(height=500)

        with chat_container:
            if not chat_history:
                st.info(
                    "👋 Start chatting by asking a question below, or use a Quick Prompt from the sidebar!"
                )
            else:
                for message in chat_history:
                    with st.chat_message(message["role"]):
                        st.markdown(message["content"])

        # Chat input at the bottom
        if prompt := st.chat_input("Ask about this job..."):
            # Add user message
            chat_history.append({"role": "user", "content": prompt})

            # Generate response
            with st.spinner("Thinking..."):
                context = f"""
                Job Title: {selected_job["title"]}
                Company: {selected_job["company"]}
                Location: {selected_job["location"]}
                Job Description: {selected_job["description"]}
                """

                system_message = f"You are a helpful assistant that answers questions about this job. Here is the job information:\n{context}"
                if (
                    st.session_state.selected_preset
                    and st.session_state.selected_preset.get("system_prompt")
                ):
                    system_message = (
                        st.session_state.selected_preset["system_prompt"]
                        + "\n\n"
                        + context
                    )

                config_manager = get_config_manager()
                client = config_manager.get_client_for_stage("chat")

                if client:
                    messages = [{"role": "system", "content": system_message}]
                    messages.extend(chat_history)
                    try:
                        response = client.chat.completions.create(
                            model=config_manager.get_config_for_stage("chat").model,
                            messages=messages,
                            temperature=0.7,
                            max_tokens=500,
                        )
                        reply = response.choices[0].message.content
                    except Exception as e:
                        reply = f"❌ Error: {str(e)}"
                else:
                    reply = (
                        "❌ Chat LLM is not configured. Please check your .env file."
                    )

                chat_history.append({"role": "assistant", "content": reply})

            st.session_state.job_chat_history[selected_job["id"]] = chat_history
            st.rerun()
