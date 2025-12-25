"""Analytics Tab for query and visualization interface."""

import logging
from datetime import datetime
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st
from modules.database import JobDatabase

logger = logging.getLogger(__name__)

# Saved queries with recommended visualizations
SAVED_QUERIES = {
    "Jobs by Site": {
        "sql": "SELECT site, COUNT(*) as count FROM jobs GROUP BY site ORDER BY count DESC",
        "viz": "pie",
        "description": "Distribution of jobs across different platforms",
    },
    "Top Skills": {
        "sql": """SELECT skill, COUNT(*) as jobs
FROM (
    SELECT json_each.value as skill
    FROM jobs, json_each(jobs.extracted_skills)
    WHERE jobs.extracted_skills IS NOT NULL 
    AND jobs.extracted_skills != ''
    AND jobs.extracted_skills != '[]'
)
GROUP BY skill 
ORDER BY jobs DESC 
LIMIT 15""",
        "viz": "hbar",
        "description": "Most frequently extracted skills from job descriptions",
    },
    "My Matched Skills": {
        "sql": """SELECT skill, COUNT(*) as jobs
FROM (
    SELECT json_each.value as skill
    FROM jobs, json_each(jobs.matched_skills)
    WHERE jobs.matched_skills IS NOT NULL 
    AND jobs.matched_skills != ''
    AND jobs.matched_skills != '[]'
)
GROUP BY skill 
ORDER BY jobs DESC 
LIMIT 15""",
        "viz": "hbar",
        "description": "Skills from your resume that match job requirements",
    },
    "Score Distribution": {
        "sql": "SELECT llm_score as score, COUNT(*) as count FROM jobs WHERE llm_score IS NOT NULL GROUP BY llm_score ORDER BY llm_score",
        "viz": "bar",
        "description": "Distribution of job match scores",
    },
    "Jobs Timeline": {
        "sql": "SELECT DATE(date_scraped) as date, COUNT(*) as count FROM jobs WHERE date_scraped IS NOT NULL GROUP BY date ORDER BY date",
        "viz": "line",
        "description": "Jobs scraped over time",
    },
    "Top Companies": {
        "sql": "SELECT company, COUNT(*) as jobs FROM jobs WHERE company IS NOT NULL GROUP BY company ORDER BY jobs DESC LIMIT 10",
        "viz": "hbar",
        "description": "Companies with most job postings",
    },
    "Key Metrics": {
        "sql": """SELECT 
    (SELECT COUNT(*) FROM jobs) as total_jobs,
    (SELECT COUNT(*) FROM applications) as applications,
    (SELECT ROUND(AVG(llm_score), 1) FROM jobs WHERE llm_score IS NOT NULL) as avg_score,
    (SELECT COUNT(*) FROM jobs WHERE llm_score >= 8) as high_matches""",
        "viz": "metric",
        "description": "Overview statistics",
    },
    "Remote vs On-site": {
        "sql": """SELECT 
    CASE WHEN is_remote = 1 THEN 'Remote' ELSE 'On-site' END as type,
    COUNT(*) as count
FROM jobs
GROUP BY is_remote""",
        "viz": "pie",
        "description": "Remote vs on-site job distribution",
    },
}


def render_analytics_tab(db: JobDatabase) -> None:
    """Render the analytics interface.

    Args:
        db: Database instance.
    """
    st.title("📊 Analytics")

    ro_conn = db.get_read_only_conn()

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

        # Query selector
        selected_query_name = st.selectbox(
            "Select a query",
            options=[""] + list(SAVED_QUERIES.keys()),
            format_func=lambda x: "-- Select a query --" if x == "" else x,
            key="saved_query_selector",
            index=0
            if st.session_state.selected_query_name == ""
            else list([""] + list(SAVED_QUERIES.keys())).index(
                st.session_state.selected_query_name
            ),
        )

        # Update session state when selection changes
        st.session_state.selected_query_name = selected_query_name

        if selected_query_name and selected_query_name != "":
            query_info = SAVED_QUERIES[selected_query_name]
            st.caption(query_info["description"])

            if st.button("📥 Load Query", width="stretch"):
                st.session_state.current_query = query_info["sql"]
                st.session_state.recommended_viz = query_info["viz"]
                st.session_state.query_version = (
                    st.session_state.get("query_version", 0) + 1
                )  # Increment to force re-render
                st.rerun()

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

        viz_types = {
            "table": "📋 Table",
            "bar": "📊 Bar Chart",
            "hbar": "📊 Horizontal Bar",
            "pie": "🥧 Pie Chart",
            "line": "📈 Line Chart",
            "metric": "🎯 Metric Cards",
        }

        # Initialize recommended viz if not exists
        if "recommended_viz" not in st.session_state:
            st.session_state.recommended_viz = "table"

        # Get index for default selection
        default_index = list(viz_types.keys()).index(st.session_state.recommended_viz)

        viz_type = st.radio(
            "Choose visualization",
            options=list(viz_types.keys()),
            format_func=lambda x: viz_types[x],
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
            elif not query_text.strip().upper().startswith("SELECT"):
                st.error("❌ Only SELECT queries are allowed for security reasons")
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
