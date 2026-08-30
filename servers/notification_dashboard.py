#!/usr/bin/env python3
"""
Governance Sessions Dashboard
==============================

Web dashboard for viewing and managing governance sessions.
Shows pending, active, and completed governance decisions.

Runs on port 8081 by default.
"""

import logging
from flask import Flask, render_template_string, request, jsonify
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
logger = logging.getLogger(__name__)

# Use unified Postgres database manager instead of direct MySQL
from core.database import get_database_manager

# Flask app
app = Flask(__name__)

# ============================================================================
# DATABASE QUERIES
# ============================================================================

def get_governance_sessions(status=None):
    """Get governance sessions from database"""

    try:
        db = get_database_manager()

        if status:
            sessions = await db.execute_query(
                """
                SELECT * FROM governance_sessions
                WHERE status = $1
                ORDER BY created_at DESC
                LIMIT 100
                """,
                params=(status,),
                fetch_all=True,
            )
        else:
            sessions = await db.execute_query(
                """
                SELECT * FROM governance_sessions
                ORDER BY created_at DESC
                LIMIT 100
                """,
                fetch_all=True,
            )

        return sessions or []

    except Exception as e:
        logger.error(f"Failed to fetch governance sessions: {e}")
        return []

def get_notifications(limit=50):
    """Get general system notifications"""

    try:
        db = get_database_manager()
        notifications = await db.execute_query(
            """
            SELECT * FROM notifications
            ORDER BY created_at DESC
            LIMIT $1
            """,
            params=(limit,),
            fetch_all=True,
        )

        return notifications or []

    except Exception as e:
        logger.error(f"Failed to fetch notifications: {e}")
        return []

def update_session_status(session_id, status, decision, notes=""):
    """Update governance session status"""

    try:
        db = get_database_manager()
        timestamp = datetime.now()

        await db.execute_query(
            """
            UPDATE governance_sessions
            SET status = $1, decision = $2, notes = $3,
                updated_at = $4
            WHERE session_id = $5
            """,
            params=(status, decision, notes, timestamp, session_id),
            commit=True,
        )

        logger.info(f"Session {session_id} updated to {status} with decision {decision}")
        return True

    except Exception as e:
        logger.error(f"Failed to update session: {e}")
        return False

# ============================================================================
# WEB ROUTES
# ============================================================================

@app.route("/")
def dashboard():
    """
    Main governance sessions dashboard
    Shows pending, active, and completed sessions
    Allows viewing details and making decisions
    """

    sessions = get_governance_sessions()
    notifications = get_notifications(limit=20)

    # Group by status
    pending = [s for s in sessions if s.get('status') == 'pending']
    active = [s for s in sessions if s.get('status') == 'active']
    completed = [s for s in sessions if s.get('status') in ['approved', 'rejected', 'deferred']]

    # Stats
    total_count = len(sessions)
    pending_count = len(pending)
    active_count = len(active)
    notification_count = len(notifications)
    approval_rate = (len([s for s in completed if s.get('decision') == 'approved']) / max(len(completed), 1)) * 100

    # Status colors
    status_colors = {
        'pending': '#FFA500',
        'active': '#4169E1',
        'approved': '#228B22',
        'rejected': '#DC143C',
        'deferred': '#808080',
        'escalated': '#FF4500',
        'reviewing': '#9370DB',
        'voting': '#4169E1',
        'timeout': '#696969'
    }

    decision_icons = {
        'approved': 'check',
        'rejected': 'times',
        'deferred': 'clock',
        'pending': 'hourglass',
        'escalated': 'exclamation',
        'timeout': 'ban',
        'voting': 'poll',
        'reviewing': 'eye',
        'unknown': 'question'
    }

    status_color = status_colors.get(request.args.get('filter'), '#4169E1')
    decision_icon = decision_icons.get(request.args.get('filter'), 'bell')

    filter_status = request.args.get('filter', 'all')

    # Filter sessions
    if filter_status and filter_status != 'all':
        filtered_sessions = [s for s in sessions if s.get('status') == filter_status or s.get('decision') == filter_status]
    else:
        filtered_sessions = sessions

    # Build sessions HTML
    sessions_html = ""
    if filtered_sessions:
        sessions_html = "<table class='sessions-table'><thead><tr><th>Session ID</th><th>Type</th><th>Decision Tier</th><th>Status</th><th>Created</th><th>Actions</th></tr></thead><tbody>"
        for session in filtered_sessions:
            session_id = session.get('session_id', 'unknown')
            session_type = session.get('session_type', 'unknown')
            decision_tier = session.get('decision_tier', 'ROUTINE')
            status = session.get('status', 'pending')
            created_at = session.get('created_at', datetime.now())

            if isinstance(created_at, str):
                created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))

            color = status_colors.get(status, '#808080')

            sessions_html += f"<tr><td><strong>{session_id[:8]}</strong></td><td>{session_type.replace('_', ' ').title()}</td><td><span class='tier-badge' style='background-color: {color};'>{decision_tier}</span></td><td><span class='status-badge' style='background-color: {color};'>{status.upper()}</span></td><td>{created_at.strftime('%Y-%m-%d %H:%M')}</td><td><button onclick=\"viewSession('{session_id}')\">View</button></td></tr>"

        sessions_html += "</tbody></table>"
    else:
        sessions_html = "<div class='empty-state'><p>No governance sessions found</p></div>"

    # Build pending HTML
    pending_html = ""
    if pending:
        for session in pending[:5]:
            session_id = session.get('session_id', 'unknown')
            session_type = session.get('session_type', 'unknown')
            tier = session.get('decision_tier', 'ROUTINE')
            created = session.get('created_at', datetime.now())

            if isinstance(created, str):
                created = datetime.fromisoformat(created.replace('Z', '+00:00'))

            tier_color = '#FFA500' if tier == 'ROUTINE' else '#FF4500' if tier == 'CRITICAL' else '#4169E1'

            pending_html += f"""
            <div class='pending-item'>
                <div class='pending-header'>
                    <span class='tier-badge' style='background-color: {tier_color};'>
                        {tier}
                    </span>
                    <span class='session-id'>{session_id[:8]}</span>
                </div>
                <div class='pending-body'>
                    <div class='session-type'>{session_type.replace('_', ' ').title()}</div>
                    <div class='session-time'>Created: {created.strftime('%Y-%m-%d %H:%M')}</div>
                    <button onclick=\"viewSession('{session_id}')\">Review</button>
                </div>
            </div>
            """
    else:
        pending_html = "<div class='empty-state'><p>No pending sessions</p></div>"

    # Build notifications HTML
    notifications_html = ""
    if notifications:
        for notif in notifications[:10]:
            notif_id = notif.get('id', 'unknown')
            notif_type = notif.get('type', 'info')
            title = notif.get('title', 'Notification')
            message = notif.get('message', '')
            created = notif.get('created_at', datetime.now())

            if isinstance(created, str):
                try:
                    created = datetime.fromisoformat(created.replace('Z', '+00:00'))
                except:
                    created = datetime.now()

            # Type colors
            type_colors = {
                'info': '#4169E1',
                'success': '#228B22',
                'warning': '#FFA500',
                'error': '#DC143C',
                'security': '#FF4500',
                'self_upgrade': '#9370DB'
            }
            type_color = type_colors.get(notif_type, '#4169E1')

            notifications_html += f"""
            <div class='notification-item' style='border-left-color: {type_color};'>
                <div class='notification-header'>
                    <span class='type-badge' style='background-color: {type_color};'>
                        {notif_type.upper()}
                    </span>
                    <span class='notification-time'>{created.strftime('%H:%M')}</span>
                </div>
                <div class='notification-title'>{title}</div>
                <div class='notification-message'>{message[:100]}{('...' if len(message) > 100 else '')}</div>
            </div>
            """
    else:
        notifications_html = "<div class='empty-state'><p>No recent notifications</p></div>"

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset='utf-8'>
    <meta name='viewport' content='width=device-width, initial-scale=1'>
    <title>Governance Sessions Dashboard</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background-color: #0f0f0f;
            color: #e0e0e0;
            padding: 20px;
            line-height: 1.6;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}
        header {{
            background-color: #1a1a1a;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            border: 1px solid #333;
        }}
        h1 {{
            font-size: 24px;
            color: #ffffff;
        }}
        .subtitle {{
            color: #888;
            font-size: 14px;
            margin-top: 5px;
        }}
        .stats {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }}
        .stat-card {{
            background-color: #1a1a1a;
            padding: 15px;
            border-radius: 8px;
            border: 1px solid #333;
        }}
        .stat-value {{
            font-size: 32px;
            font-weight: bold;
            color: #4169E1;
        }}
        .stat-label {{
            color: #888;
            font-size: 14px;
            margin-top: 5px;
        }}
        .main-content {{
            display: grid;
            grid-template-columns: 300px 1fr;
            gap: 20px;
        }}
        .sidebar {{
            background-color: #1a1a1a;
            padding: 20px;
            border-radius: 8px;
            border: 1px solid #333;
            height: fit-content;
        }}
        .sidebar h2 {{
            font-size: 18px;
            margin-bottom: 15px;
            color: #ffffff;
        }}
        .pending-item {{
            background-color: #242424;
            padding: 12px;
            border-radius: 6px;
            margin-bottom: 10px;
            border-left: 3px solid #FFA500;
        }}
        .pending-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
        }}
        .tier-badge {{
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: bold;
            color: #ffffff;
            text-transform: uppercase;
        }}
        .session-id {{
            font-family: monospace;
            color: #888;
            font-size: 12px;
        }}
        .session-type {{
            color: #e0e0e0;
            font-size: 14px;
            margin-bottom: 4px;
        }}
        .session-time {{
            color: #888;
            font-size: 12px;
            margin-bottom: 8px;
        }}
        .notification-item {{
            background-color: #242424;
            padding: 10px;
            border-radius: 6px;
            margin-bottom: 8px;
            border-left: 3px solid #4169E1;
        }}
        .notification-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 6px;
        }}
        .type-badge {{
            padding: 3px 6px;
            border-radius: 3px;
            font-size: 10px;
            font-weight: bold;
            color: #ffffff;
        }}
        .notification-time {{
            font-size: 11px;
            color: #666;
        }}
        .notification-title {{
            color: #e0e0e0;
            font-size: 13px;
            font-weight: 600;
            margin-bottom: 4px;
        }}
        .notification-message {{
            color: #999;
            font-size: 12px;
            line-height: 1.4;
        }}
        .content-area {{
            background-color: #1a1a1a;
            padding: 20px;
            border-radius: 8px;
            border: 1px solid #333;
        }}
        .filters {{
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }}
        .filter-btn {{
            padding: 8px 16px;
            background-color: #242424;
            border: 1px solid #333;
            border-radius: 6px;
            color: #e0e0e0;
            cursor: pointer;
            font-size: 14px;
            transition: all 0.2s;
        }}
        .filter-btn:hover {{
            background-color: #2a2a2a;
            border-color: #4169E1;
        }}
        .filter-btn.active {{
            background-color: #4169E1;
            border-color: #4169E1;
            color: #ffffff;
        }}
        .sessions-table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
        }}
        .sessions-table th {{
            background-color: #242424;
            padding: 12px;
            text-align: left;
            font-size: 13px;
            color: #888;
            font-weight: 600;
            border-bottom: 2px solid #333;
        }}
        .sessions-table td {{
            padding: 12px;
            border-bottom: 1px solid #2a2a2a;
            font-size: 13px;
        }}
        .sessions-table tr:hover {{
            background-color: #242424;
        }}
        .status-badge {{
            padding: 4px 10px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: bold;
            color: #ffffff;
            display: inline-block;
        }}
        button {{
            background-color: #4169E1;
            color: #ffffff;
            border: none;
            padding: 6px 12px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 13px;
            transition: background-color 0.2s;
        }}
        button:hover {{
            background-color: #2952CC;
        }}
        .empty-state {{
            text-align: center;
            padding: 40px;
            color: #888;
        }}
        @media (max-width: 768px) {{
            .main-content {{
                grid-template-columns: 1fr;
            }}
        }}
    </style>
</head>
<body>
    <div class='container'>
        <!-- Header -->
        <header>
            <h1>Governance Sessions Dashboard</h1>
            <div class='subtitle'>View and manage governance decisions</div>
        </header>

        <!-- Stats -->
        <div class='stats'>
            <div class='stat-card'>
                <div class='stat-value'>{total_count}</div>
                <div class='stat-label'>Total Sessions</div>
            </div>
            <div class='stat-card'>
                <div class='stat-value'>{pending_count}</div>
                <div class='stat-label'>Pending Review</div>
            </div>
            <div class='stat-card'>
                <div class='stat-value'>{notification_count}</div>
                <div class='stat-label'>Notifications</div>
            </div>
            <div class='stat-card'>
                <div class='stat-value'>{approval_rate:.0f}%</div>
                <div class='stat-label'>Approval Rate</div>
            </div>
        </div>

        <!-- Main Content -->
        <div class='main-content'>
            <!-- Sidebar -->
            <div class='sidebar'>
                <h2>Pending Review</h2>
                {pending_html}

                <h2 style='margin-top: 30px;'>Recent Notifications</h2>
                {notifications_html}
            </div>

            <!-- Content Area -->
            <div class='content-area'>
                <h2>All Sessions</h2>

                <!-- Filters -->
                <div class='filters'>
                    <button class='filter-btn {("active" if filter_status == "all" else "")}' onclick=\"filterSessions('all')\">All</button>
                    <button class='filter-btn {("active" if filter_status == "pending" else "")}' onclick=\"filterSessions('pending')\">Pending</button>
                    <button class='filter-btn {("active" if filter_status == "active" else "")}' onclick=\"filterSessions('active')\">Active</button>
                    <button class='filter-btn {("active" if filter_status == "approved" else "")}' onclick=\"filterSessions('approved')\">Approved</button>
                    <button class='filter-btn {("active" if filter_status == "rejected" else "")}' onclick=\"filterSessions('rejected')\">Rejected</button>
                </div>

                <!-- Sessions Table -->
                {sessions_html}
            </div>
        </div>

        <div style='margin-top: 30px; text-align: center; color: #555;'>
            TorinAI Governance Dashboard - Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        </div>
    </div>

    <script>
        function filterSessions(status) {{
            window.location.href = '/?filter=' + status;
        }}

        function viewSession(sessionId) {{
            const confirmView = confirm('View session ' + sessionId.substring(0, 8) + (sessionId.length > 8 ? '...' : '') + '?');

            if (!confirmView) {{
                return;
            }}

            // Open session details (could be a modal or new page)
            fetch('/api/session/' + sessionId, {{
                method: 'GET',
                headers: {{
                    'Content-Type': 'application/json'
                }}
            }})
            .then(response => response.json())
            .then(data => {{
                alert('Session details:\\n' + JSON.stringify(data, null, 2));
            }})
            .catch(error => {{
                alert('Error loading session: ' + error);
            }});
        }}
    </script>
</body>
</html>"""

    return render_template_string(html)

# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.route("/api/session/<session_id>", methods=['GET', 'POST'])
def session_detail(session_id, decision=None):
    """
    Get or update governance session
    GET: Returns session details
    POST: Updates session decision
    """

    if request.method == 'GET':
        sessions = get_governance_sessions()
        session = next((s for s in sessions if s.get('session_id') == session_id), None)

        if session:
            return jsonify(session)
        else:
            return jsonify({"error": "Session not found"}), 404

    else:  # POST
        # Update session
        data = request.json
        decision = data.get('decision')
        notes = data.get('notes', '')

        # Validate decision
        if decision not in ['approved', 'rejected', 'deferred']:
            return jsonify({"error": "Invalid decision"}), 400

        logger.info(f"Updating session {session_id} with decision {decision} and notes {notes}")

        # Update database
        success = update_session_status(session_id, decision, decision, notes)

        if success:
            return jsonify({"success": True, "session_id": session_id, "decision": decision})
        else:
            return jsonify({"error": "Failed to update session"}), 500

@app.route("/health")
def health():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "service": "governance_dashboard"})

# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    logger.info("Starting Governance Sessions Dashboard")
    logger.info("Access at: http://localhost:8081")

    app.run(host='0.0.0.0', port=8081, debug=True, use_reloader=False)
