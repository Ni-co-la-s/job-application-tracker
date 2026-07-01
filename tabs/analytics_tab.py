"""Analytics Tab for query and visualization interface."""

import json
import logging
from datetime import datetime
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

from constants import QUERIES_FILE
from modules.database import JobDatabase

logger = logging.getLogger(__name__)

VIZ_TYPES = {
    "table": "📋 Table",
    "bar": "📊 Bar Chart",
    "hbar": "📊 Horizontal Bar",
    "pie": "🥧 Pie Chart",
    "line": "📈 Line Chart",
    "metric": "🎯 Metric Cards",
}


def save_queries() -> None:
    """Persist saved analytics queries to the queries JSON file."""
    with open(QUERIES_FILE, "w", encoding="utf-8") as f:
        json.dump(st.session_state.saved_queries, f, indent=4)


def render_analytics_tab(db: JobDatabase) -> None:
    """Render the analytics interface.

    Args:
        db: Database instance.
    """
    st.title("📊 Analytics")

    ro_conn = db.get_read_only_conn()

    # Initialize session state for saved queries
    if "saved_queries" not in st.session_state:
        try:
            with open(QUERIES_FILE, "r", encoding="utf-8") as f:
                saved_queries = json.load(f)
                st.session_state.saved_queries = (
                    saved_queries if isinstance(saved_queries, dict) else {}
                )
        except (FileNotFoundError, json.JSONDecodeError):
            st.session_state.saved_queries = {}

    # Schema reference at top (collapsible)
    with st.expander("📚 Database Schema Reference"):
        render_schema_reference(ro_conn)

    # Main layout: left sidebar with queries, right area with results
    col_left, col_right = st.columns([1, 2])

    # ==================== LEFT COLUMN: Query Builder ====================
    with col_left:
        st.subheader("💾 Saved Queries")

        # Initialize session state
        if "selected_query_name" not in st.session_state:
            st.session_state.selected_query_name = ""

        saved_query_names = list(st.session_state.saved_queries.keys())
        if st.session_state.selected_query_name not in saved_query_names:
            st.session_state.selected_query_name = ""

        query_options = [""] + saved_query_names

        # Query selector
        selected_query_name = st.selectbox(
            "Select a query",
            options=query_options,
            format_func=lambda x: "-- Select a query --" if x == "" else x,
            key="saved_query_selector",
            index=query_options.index(st.session_state.selected_query_name),
        )

        # Update session state when selection changes
        st.session_state.selected_query_name = selected_query_name

        if selected_query_name and selected_query_name != "":
            query_info = st.session_state.saved_queries[selected_query_name]
            st.caption(query_info.get("description", ""))

            if st.button("📥 Load Query", width="stretch"):
                st.session_state.current_query = query_info.get("sql", "")
                st.session_state.recommended_viz = query_info.get("viz", "table")
                st.session_state.query_version = (
                    st.session_state.get("query_version", 0) + 1
                )  # Increment to force re-render
                st.rerun()

        st.divider()

        # Query management (collapsed by default)
        with st.expander("⚙️ Manage Queries"):
            query_action = st.radio(
                "Action",
                ["Create New", "Edit/Delete"],
                horizontal=True,
                key="query_action_radio",
            )

            if query_action == "Create New":
                with st.form("create_query_form", clear_on_submit=True):
                    new_name = st.text_input(
                        "Query Name", placeholder="e.g., Top Remote Jobs"
                    )
                    new_sql = st.text_area(
                        "SQL Query",
                        placeholder="SELECT * FROM jobs WHERE is_remote = 1 LIMIT 10",
                        height=100,
                    )
                    new_viz = st.selectbox(
                        "Visualization Type",
                        options=list(VIZ_TYPES.keys()),
                        format_func=lambda x: VIZ_TYPES[x],
                    )
                    new_description = st.text_input(
                        "Description",
                        placeholder="Brief description of what this query shows",
                    )

                    if st.form_submit_button("Create Query", width="stretch"):
                        if new_name and new_sql and new_description:
                            if new_name in st.session_state.saved_queries:
                                st.error(f"Query '{new_name}' already exists")
                            else:
                                st.session_state.saved_queries[new_name] = {
                                    "sql": new_sql,
                                    "viz": new_viz,
                                    "description": new_description,
                                }
                                save_queries()
                                st.toast(f"✓ Created '{new_name}'")
                                st.rerun()
                        else:
                            st.error("All fields are required")

            else:  # Edit/Delete
                if st.session_state.saved_queries:
                    query_to_edit = st.selectbox(
                        "Select query",
                        options=list(st.session_state.saved_queries.keys()),
                        key="query_to_edit",
                    )

                    if query_to_edit:
                        query = st.session_state.saved_queries[query_to_edit]
                        current_viz = query.get("viz", "table")
                        if current_viz not in VIZ_TYPES:
                            current_viz = "table"

                        with st.form("edit_query_form"):
                            edit_name = st.text_input("Name", value=query_to_edit)
                            edit_sql = st.text_area(
                                "SQL Query", value=query.get("sql", ""), height=100
                            )
                            edit_viz = st.selectbox(
                                "Visualization Type",
                                options=list(VIZ_TYPES.keys()),
                                index=list(VIZ_TYPES.keys()).index(current_viz),
                                format_func=lambda x: VIZ_TYPES[x],
                            )
                            edit_description = st.text_input(
                                "Description", value=query.get("description", "")
                            )

                            col1, col2 = st.columns(2)
                            with col1:
                                if st.form_submit_button("💾 Update", width="stretch"):
                                    if (
                                        not edit_name
                                        or not edit_sql
                                        or not edit_description
                                    ):
                                        st.error("All fields are required")
                                    elif (
                                        edit_name != query_to_edit
                                        and edit_name in st.session_state.saved_queries
                                    ):
                                        st.error(f"'{edit_name}' already exists")
                                    else:
                                        if edit_name != query_to_edit:
                                            del st.session_state.saved_queries[
                                                query_to_edit
                                            ]
                                        st.session_state.saved_queries[edit_name] = {
                                            "sql": edit_sql,
                                            "viz": edit_viz,
                                            "description": edit_description,
                                        }
                                        st.session_state.selected_query_name = edit_name
                                        save_queries()
                                        st.toast("✓ Updated")
                                        st.rerun()

                            with col2:
                                if st.form_submit_button("🗑️ Delete", width="stretch"):
                                    del st.session_state.saved_queries[query_to_edit]
                                    if (
                                        st.session_state.selected_query_name
                                        == query_to_edit
                                    ):
                                        st.session_state.selected_query_name = ""
                                    save_queries()
                                    st.toast("✓ Deleted")
                                    st.rerun()
                else:
                    st.info("No queries yet. Create one above!")

        st.divider()

        # SQL Query Editor
        st.subheader("✏️ SQL Query")

        # Initialize session state for query if not exists
        if "current_query" not in st.session_state:
            st.session_state.current_query = ""
        if "query_version" not in st.session_state:
            st.session_state.query_version = 0

        query_text = st.text_area(
            "Enter your query",
            value=st.session_state.current_query,
            height=200,
            placeholder="SELECT * FROM jobs LIMIT 10",
            key=f"query_editor_input_{st.session_state.query_version}",  # Dynamic key forces re-render
        )

        st.divider()

        # Visualization Type Selector
        st.subheader("📊 Visualization Type")

        # Initialize recommended viz if not exists
        if "recommended_viz" not in st.session_state:
            st.session_state.recommended_viz = "table"
        if st.session_state.recommended_viz not in VIZ_TYPES:
            st.session_state.recommended_viz = "table"

        # Get index for default selection
        default_index = list(VIZ_TYPES.keys()).index(st.session_state.recommended_viz)

        viz_type = st.radio(
            "Choose visualization",
            options=list(VIZ_TYPES.keys()),
            format_func=lambda x: VIZ_TYPES[x],
            index=default_index,
            key=f"viz_type_selector_{st.session_state.query_version}",  # Dynamic key to force update
        )

        st.divider()

        # Run button
        run_query = st.button("▶️ Run Query", type="primary", width="stretch")

    # ==================== RIGHT COLUMN: Results ====================
    with col_right:
        st.subheader("📊 Results")

        if run_query:
            if not query_text or query_text.strip() == "":
                st.warning("⚠️ Please enter a SQL query first")
            else:
                execute_query_with_viz(ro_conn, query_text, viz_type)
        elif st.session_state.get("last_result") is not None:
            # Show last result if available
            df, last_viz = st.session_state.last_result
            render_visualization(df, last_viz)
        else:
            st.info(
                "👈 Select a saved query or write your own SQL, choose a visualization type, then click 'Run Query'"
            )

            # Show some helpful tips
            st.markdown("---")
            st.markdown("### 💡 Quick Tips")
            st.markdown("""
            - **Table**: Works with any query result
            - **Bar/Pie Charts**: Need 2 columns (category, value)
            - **Line Chart**: Best with date/time series data
            - **Metric Cards**: Show 1-4 key numbers
            - **Horizontal Bar**: Good for long labels
            """)
        ro_conn.close()


def render_schema_reference(conn: Any) -> None:
    """Render database schema with examples.

    Args:
        conn: Database connection.
    """
    tables = ["jobs", "applications", "interview_stages"]

    for table in tables:
        with st.expander(f"📋 **{table}**"):
            # Get columns
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA table_info({table})")
            columns = cursor.fetchall()

            # Get row count
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            row_count = cursor.fetchone()[0]

            st.caption(f"**{row_count} rows**")

            # Display columns
            col_data = []
            for col in columns:
                col_data.append(
                    {
                        "Column": col[1],
                        "Type": col[2],
                        "Nullable": "Yes" if not col[3] else "No",
                    }
                )

            df_cols = pd.DataFrame(col_data)
            st.dataframe(df_cols, hide_index=True, width="stretch")

            # Show one example row (truncated)
            try:
                cursor.execute(f"SELECT * FROM {table} LIMIT 1")
                example_row = cursor.fetchone()
                if example_row:
                    st.caption("**Example row (truncated):**")
                    example_data = {}
                    for i, col in enumerate(columns):
                        value = example_row[i]
                        if value and isinstance(value, str) and len(value) > 50:
                            value = value[:50] + "..."
                        example_data[col[1]] = value
                    st.json(example_data, expanded=False)
            except Exception:
                pass


def execute_query_with_viz(conn: Any, query: str, viz_type: str) -> None:
    """Execute query and render with chosen visualization.

    Args:
        conn: Database connection.
        query: SQL query string.
        viz_type: Visualization type.
    """
    try:
        df = pd.read_sql_query(query, conn)

        # Store result in session state
        st.session_state.last_result = (df, viz_type)

        if df.empty:
            st.warning("⚠️ Query returned no results")
            return

        # Show data info
        st.success(
            f"✓ Query executed successfully - {len(df)} rows × {len(df.columns)} columns"
        )

        with st.expander("ℹ️ Data Structure"):
            col_info = []
            for col in df.columns:
                dtype = df[col].dtype
                col_info.append(
                    {
                        "Column": col,
                        "Type": str(dtype),
                        "Non-null": df[col].notna().sum(),
                    }
                )
            st.dataframe(pd.DataFrame(col_info), hide_index=True)

        # Validate and render
        render_visualization(df, viz_type)

    except Exception as e:
        st.error(f"❌ Query error: {e}")


def render_visualization(df: pd.DataFrame, viz_type: str) -> None:
    """Render visualization based on type with validation.

    Args:
        df: DataFrame with query results.
        viz_type: Visualization type.
    """

    # Validation and rendering
    if viz_type == "table":
        render_table(df)

    elif viz_type == "bar":
        validate_and_render_bar(df, orientation="v")

    elif viz_type == "hbar":
        validate_and_render_bar(df, orientation="h")

    elif viz_type == "pie":
        validate_and_render_pie(df)

    elif viz_type == "line":
        validate_and_render_line(df)

    elif viz_type == "metric":
        validate_and_render_metric(df)


def render_table(df: pd.DataFrame) -> None:
    """Render as table (always works).

    Args:
        df: DataFrame to display.
    """
    st.dataframe(df, width="stretch", height=500)

    # Export button
    csv = df.to_csv(index=False)
    st.download_button(
        "📥 Download CSV",
        data=csv,
        file_name=f"query_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
    )


def validate_and_render_bar(df: pd.DataFrame, orientation: str = "v") -> None:
    """Validate and render bar chart.

    Args:
        df: DataFrame with data.
        orientation: 'v' for vertical, 'h' for horizontal.
    """
    # Need at least 2 columns
    if len(df.columns) < 2:
        st.error(
            f"❌ Bar chart needs at least 2 columns (category and value). Your query returned {len(df.columns)} column(s)."
        )
        st.info(
            "💡 Try: `SELECT category_column, COUNT(*) as count FROM table GROUP BY category_column`"
        )
        return

    # Check if second column is numeric
    if not pd.api.types.is_numeric_dtype(df.iloc[:, 1]):
        st.error(
            f"❌ Bar chart needs numeric values in the second column. Column '{df.columns[1]}' contains {df.iloc[:, 1].dtype}."
        )
        st.info("💡 Use COUNT(*), SUM(), AVG(), etc. to create numeric values")
        return

    # Warn if too many rows
    if len(df) > 50:
        st.warning(
            f"⚠️ Chart has {len(df)} bars. Consider using LIMIT or grouping for better readability."
        )

    # Render
    try:
        if orientation == "h":
            fig = px.bar(df, x=df.columns[1], y=df.columns[0], orientation="h")
            fig.update_layout(height=max(400, len(df) * 25))
        else:
            fig = px.bar(df, x=df.columns[0], y=df.columns[1])
            fig.update_layout(height=500)

        st.plotly_chart(fig, width="stretch")

        # Show raw data option
        with st.expander("📋 View Raw Data"):
            st.dataframe(df, width="stretch")

    except Exception as e:
        st.error(f"❌ Error rendering chart: {e}")


def validate_and_render_pie(df: pd.DataFrame) -> None:
    """Validate and render pie chart.

    Args:
        df: DataFrame with data.
    """
    # Need exactly 2 columns
    if len(df.columns) != 2:
        st.error(
            f"❌ Pie chart needs exactly 2 columns (category and value). Your query returned {len(df.columns)} columns."
        )
        st.info(
            "💡 Try: `SELECT category, COUNT(*) as count FROM table GROUP BY category`"
        )
        return

    # Check if second column is numeric
    if not pd.api.types.is_numeric_dtype(df.iloc[:, 1]):
        st.error(
            f"❌ Pie chart needs numeric values. Column '{df.columns[1]}' contains {df.iloc[:, 1].dtype}."
        )
        return

    # Check for negative values
    if (df.iloc[:, 1] < 0).any():
        st.error("❌ Pie chart cannot display negative values.")
        return

    # Warn if too many slices
    if len(df) > 20:
        st.warning(
            f"⚠️ Pie chart has {len(df)} slices. Consider showing only top N with: `ORDER BY value DESC LIMIT 10`"
        )

    if len(df) < 2:
        st.error("❌ Pie chart needs at least 2 categories.")
        return

    # Render
    try:
        fig = px.pie(df, values=df.columns[1], names=df.columns[0], hole=0.4)
        fig.update_layout(height=500)
        st.plotly_chart(fig, width="stretch")

        with st.expander("📋 View Raw Data"):
            st.dataframe(df, width="stretch")

    except Exception as e:
        st.error(f"❌ Error rendering chart: {e}")


def validate_and_render_line(df: pd.DataFrame) -> None:
    """Validate and render line chart.

    Args:
        df: DataFrame with data.
    """
    # Need at least 2 columns
    if len(df.columns) < 2:
        st.error(
            f"❌ Line chart needs at least 2 columns (x-axis and y-axis). Your query returned {len(df.columns)} column(s)."
        )
        return

    # Need at least 2 data points
    if len(df) < 2:
        st.error(
            f"❌ Line chart needs at least 2 data points. Your query returned {len(df)} row(s)."
        )
        st.info("💡 Make sure your query returns multiple rows (e.g., group by date)")
        return

    # Check if y-axis is numeric
    if not pd.api.types.is_numeric_dtype(df.iloc[:, 1]):
        st.error(
            f"❌ Line chart needs numeric values for y-axis. Column '{df.columns[1]}' contains {df.iloc[:, 1].dtype}."
        )
        return

    # Render
    try:
        fig = px.line(df, x=df.columns[0], y=df.columns[1], markers=True)

        # Add more lines if more columns
        for col in df.columns[2:]:
            if pd.api.types.is_numeric_dtype(df[col]):
                fig.add_scatter(
                    x=df[df.columns[0]], y=df[col], mode="lines+markers", name=col
                )

        fig.update_layout(height=500)
        st.plotly_chart(fig, width="stretch")

        with st.expander("📋 View Raw Data"):
            st.dataframe(df, width="stretch")

    except Exception as e:
        st.error(f"❌ Error rendering chart: {e}")


def validate_and_render_metric(df: pd.DataFrame) -> None:
    """Validate and render metric cards.

    Args:
        df: DataFrame with data.
    """
    # Check row count
    if len(df) > 4:
        st.error(
            f"❌ Metric cards work best with 1-4 values. Your query returned {len(df)} rows."
        )
        st.info(
            "💡 Add `LIMIT 4` to your query, or use aggregation to get single values"
        )
        return

    if len(df) == 0:
        st.error("❌ No data to display")
        return

    # Render metrics
    try:
        # If single row with multiple columns, show each column as a metric
        if len(df) == 1:
            cols = st.columns(min(len(df.columns), 4))
            for i, col_name in enumerate(df.columns):
                with cols[i]:
                    value = df.iloc[0][col_name]
                    st.metric(col_name.replace("_", " ").title(), value)

        # If multiple rows with 2 columns, show label + value
        elif len(df.columns) >= 2:
            cols = st.columns(min(len(df), 4))
            for i, row in df.iterrows():
                with cols[i]:
                    label = str(row.iloc[0])
                    value = row.iloc[1]
                    st.metric(label, value)

        # If single column, show each row as a metric
        else:
            cols = st.columns(min(len(df), 4))
            for i, row in df.iterrows():
                with cols[i]:
                    st.metric(f"Value {i + 1}", row.iloc[0])

        st.divider()

        with st.expander("📋 View Raw Data"):
            st.dataframe(df, width="stretch")

    except Exception as e:
        st.error(f"❌ Error rendering metrics: {e}")
