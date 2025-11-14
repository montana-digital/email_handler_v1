"""Email Butler v1 - Main Streamlit Application Entry Point."""

import sys
from pathlib import Path
from datetime import datetime

# Add project root to Python path so 'src' module can be imported
project_root = Path(__file__).parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import streamlit as st
from src.config.settings import get_settings
from src.database.session import init_database, get_engine, get_session_factory
from src.utils.logger import get_logger
from src.utils.session_manager import ensure_initialized
from src.ui.components.sidebar import get_logo_path
from sqlalchemy import inspect
from src.database.models import EmailTemplate, BlackBookContact, EmailGenerationSession, ReportedRecord

logger = get_logger(__name__)

# Application version
APP_VERSION = "1.1.2"

# Page configuration
# Use SPEAR logo as favicon
favicon_path = Path(__file__).parent.parent / "SPEAR_transparent_cropped.png"
st.set_page_config(
    page_title="Email Butler",
    page_icon=str(favicon_path) if favicon_path.exists() else "📧",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize settings
settings = get_settings()

# Initialize database
init_database()


def get_database_stats():
    """Get database statistics."""
    try:
        engine = get_engine()
        inspector = inspect(engine)
        
        # Get table count
        table_names = inspector.get_table_names()
        table_count = len(table_names)
        
        # Get database file size
        db_path = Path(settings.database_path)
        db_size_bytes = db_path.stat().st_size if db_path.exists() else 0
        db_size_mb = db_size_bytes / (1024 * 1024)
        
        # Get counts from database
        factory = get_session_factory()
        session = factory()
        try:
            # Count templates
            template_count = session.query(EmailTemplate).count()
            
            # Count contacts
            contact_count = session.query(BlackBookContact).count()
            
            # Count total records across all tables
            total_records = (
                session.query(EmailTemplate).count() +
                session.query(BlackBookContact).count() +
                session.query(EmailGenerationSession).count() +
                session.query(ReportedRecord).count()
            )
        finally:
            session.close()
        
        return {
            "template_count": template_count,
            "contact_count": contact_count,
            "database_size_mb": round(db_size_mb, 2),
            "table_count": table_count,
            "total_records": total_records
        }
    except Exception as e:
        logger.error("Error getting database stats", error=str(e))
        return {
            "template_count": 0,
            "contact_count": 0,
            "database_size_mb": 0,
            "table_count": 0,
            "total_records": 0
        }


def get_python_info():
    """Get Python version and key dependencies."""
    import sys
    from importlib.metadata import version, PackageNotFoundError
    
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    
    # Key dependencies
    key_deps = [
        "streamlit",
        "pandas",
        "sqlalchemy",
        "pydantic",
        "pillow",
        "structlog"
    ]
    
    dependencies = {}
    for dep in key_deps:
        try:
            dependencies[dep] = version(dep)
        except PackageNotFoundError:
            dependencies[dep] = "Not installed"
    
    return {
        "python_version": python_version,
        "dependencies": dependencies
    }


def get_deployment_info():
    """Get deployment information."""
    # Try to get git info if available
    try:
        import subprocess
        result = subprocess.run(
            ["git", "log", "-1", "--format=%cd", "--date=short"],
            capture_output=True,
            text=True,
            cwd=project_root
        )
        if result.returncode == 0 and result.stdout.strip():
            last_deployed = result.stdout.strip()
        else:
            # Fallback to file modification time
            db_path = Path(settings.database_path)
            if db_path.exists():
                last_deployed = datetime.fromtimestamp(db_path.stat().st_mtime).strftime("%Y-%m-%d")
            else:
                last_deployed = "N/A"
    except Exception:
        # Fallback to database file modification time
        try:
            db_path = Path(settings.database_path)
            if db_path.exists():
                last_deployed = datetime.fromtimestamp(db_path.stat().st_mtime).strftime("%Y-%m-%d")
            else:
                last_deployed = "N/A"
        except Exception:
            last_deployed = "N/A"
    
    return {
        "last_deployed": last_deployed
    }


def main():
    """Main application entry point."""
    # Ensure app is initialized (will show warning and redirect if not)
    ensure_initialized()
    
    # Sidebar
    from src.ui.components.sidebar import render_sidebar
    render_sidebar()
    
    # Get logo path
    logo_path = get_logo_path()
    
    # Inject CSS animations for reveal effects
    from src.ui.styles.animations import inject_reveal_animations
    inject_reveal_animations()
    
    # Container 1: Header with Logo
    with st.container():
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.markdown("# <span class='gold-shimmer'>Email Butler</span> <span class='silver-shimmer' style='font-size: 0.6em;'>part of the SPEAR toolbelt</span>", unsafe_allow_html=True)
            st.markdown(f"**Version:** {APP_VERSION}")
            st.markdown("""
            **Description:** Generate bulk Email templates from CSVs.  
            Preconfigure your template, add your contacts and provide your dataset.  
            The Butler will handle the rest.
            """)
        
        with col2:
            if logo_path:
                try:
                    st.image(str(logo_path), use_container_width=True)
                except Exception:
                    st.write("📧 Logo")
            else:
                st.write("📧 Logo")
    
    st.divider()
    
    # Container 2: Database Stats
    with st.container():
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.markdown("### Usage Instructions")
            st.markdown("""
            1. Create email templates in the **Email Templates** page
            2. Add contacts to your **Black Book** directory
            3. Upload CSV data and images in the **Data Processor** page
            4. Preview and generate emails with your data
            5. Configure settings and manage your database in **Settings**
            """)
        
        with col2:
            st.markdown("### Database Stats")
            stats = get_database_stats()
            st.markdown(f"""
            **Number of Templates:** {stats["template_count"]}
            
            **Number of Contacts:** {stats["contact_count"]}
            
            **Database Size:** {stats['database_size_mb']} MB
            
            **Table Count:** {stats["table_count"]}
            
            **Total Data Records:** {stats["total_records"]}
            """)
    
    st.divider()
    
    # Container 3: About App and System Info
    with st.container():
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("### About App")
            st.markdown("""
            **Developer:** Demitri Aleksejeva
            
            **Support:** Contact for Assistance
            
            **License:** Opensource
            """)
        
        with col2:
            st.markdown("### System Information")
            python_info = get_python_info()
            deployment_info = get_deployment_info()
            
            st.write(f"**Python Version:** {python_info['python_version']}")
            st.write("**Key Dependencies:**")
            for dep, version in python_info['dependencies'].items():
                st.write(f"  - {dep}: {version}")
            
            st.write(f"**Last Deployed:** {deployment_info['last_deployed']}")


if __name__ == "__main__":
    main()

