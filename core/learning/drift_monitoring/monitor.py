from __future__ import annotations
import os
import json
import pandas as pd
import logging
import asyncio
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Callable
from pathlib import Path

from evidently import Report
from evidently.presets import DataDriftPreset
from evidently.core.datasets import ColumnMapping

logger = logging.getLogger(__name__)

@dataclass
class Schema:
    datetime_column: Optional[str] = None
    target_column: Optional[str] = None
    prediction_column: Optional[str] = None
    categorical_features: Optional[List[str]] = None
    numerical_features: Optional[List[str]] = None

def build_column_mapping(schema: Schema) -> ColumnMapping:
    return ColumnMapping(
        target=schema.target_column,
        prediction=schema.prediction_column,
        numerical_features=schema.numerical_features or None,
        categorical_features=schema.categorical_features or None,
        datetime=schema.datetime_column
    )

def load_csv(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Missing CSV: {path}")
    df = pd.read_csv(path)
    return df

def run_drift_report(
    reference: pd.DataFrame,
    current: pd.DataFrame,
    schema: Schema,
    output_dir: str,
    report_html: str,
    report_json: str,
) -> dict:
    os.makedirs(output_dir, exist_ok=True)
    mapping = build_column_mapping(schema)
    report = Report(metrics=[DataDriftPreset()])
    
    # Run the report and get snapshot
    snapshot = report.run(reference_data=reference, current_data=current)
    
    # Save artifacts using snapshot methods
    html_path = os.path.join(output_dir, report_html)
    json_path = os.path.join(output_dir, report_json)
    snapshot.save_html(html_path)
    snapshot.save_json(json_path)
    
    # Return full JSON to caller
    with open(json_path, "r") as f:
        result = json.load(f)
    return result

def summarize_drift(result_json: dict) -> dict:
    """
    Extracts a compact summary:
      - share of drifted features
      - per-feature drift scores (PSI where present)
    """
    summary = {
        "dataset_drift": None,
        "share_drifted_features": None,
        "features": {},
    }
    try:
        metrics = result_json["metrics"]
        # Locate the DataDriftPreset metric block
        drift_block = next(m for m in metrics if "DataDriftTable" in str(m.get("metric")) or "DataDriftPreset" in str(m.get("metric", "")) or m.get("type") == "DataDriftTable")
    except StopIteration:
        # Evidently JSON schema may change; fall back to scanning
        drift_block = metrics[0] if metrics else {}

    # Try common fields
    # Different evidently versions structure differ; handle robustly
    value = drift_block.get("result") or drift_block.get("value") or {}
    summary["dataset_drift"] = value.get("dataset_drift")
    summary["share_drifted_features"] = value.get("share_of_drifted_features")

    # Per-feature if available
    for feat in (value.get("drift_by_columns") or {}).keys():
        feat_info = value["drift_by_columns"][feat]
        # collect common stats
        stattest = feat_info.get("stattest_name")
        drift_score = feat_info.get("drift_score")
        drift_detected = feat_info.get("drift_detected")
        summary["features"][feat] = {
            "drift_score": drift_score,
            "drift_detected": drift_detected,
            "stattest": stattest,
        }
    return summary

def evaluate_thresholds(summary: dict, psi_warn: float, psi_fail: float, share_warn: float, share_fail: float) -> dict:
    per_feat = summary.get("features", {})
    drift_scores = [v.get("drift_score") for v in per_feat.values() if v.get("drift_score") is not None]
    max_psi = max(drift_scores) if drift_scores else 0.0
    share = summary.get("share_drifted_features") or 0.0
    status = "ok"
    reasons = []
    if max_psi >= psi_warn or share >= share_warn:
        status = "warn"
        reasons.append(f"max_psi={max_psi:.3f} share_drifted={share:.3f}")
    if max_psi >= psi_fail or share >= share_fail:
        status = "fail"
    return {"status": status, "max_psi": max_psi, "share_drifted": share, "reasons": reasons}

def write_alert(output_dir: str, filename: str, status: str, details: dict):
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, filename)
    with open(path, "w") as f:
        f.write(f"STATUS: {status}\n")
        for k, v in details.items():
            f.write(f"{k}: {v}\n")
    return path

def retrain_model(current_csv: str, output_dir: str) -> str:
    """
    Full model retraining implementation.
    Replaces the previous stub with complete retraining pipeline.
    """
    import pandas as pd
    import numpy as np
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import classification_report
    import joblib
    import os
    
    try:
        # Load current data
        df = pd.read_csv(current_csv)
        logger.info(f"Loaded {len(df)} samples for retraining")
        
        # Prepare features and target
        # Assume last column is target, rest are features
        X = df.iloc[:, :-1]
        y = df.iloc[:, -1]
        
        # Handle non-numeric data
        for col in X.columns:
            if X[col].dtype == 'object':
                X[col] = pd.Categorical(X[col]).codes
        
        # Split data
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )
        
        # Train model
        model = RandomForestClassifier(
            n_estimators=100,
            max_depth=10,
            random_state=42,
            n_jobs=-1
        )
        
        logger.info("Starting model training...")
        model.fit(X_train, y_train)
        
        # Evaluate model
        train_score = model.score(X_train, y_train)
        test_score = model.score(X_test, y_test)
        
        logger.info(f"Model performance - Train: {train_score:.4f}, Test: {test_score:.4f}")
        
        # Save model
        os.makedirs(output_dir, exist_ok=True)
        model_path = os.path.join(output_dir, "retrained_model.pkl")
        joblib.dump(model, model_path)
        
        # Save metadata
        metadata = {
            "timestamp": datetime.now().isoformat(),
            "samples_used": len(df),
            "train_accuracy": float(train_score),
            "test_accuracy": float(test_score),
            "feature_columns": list(X.columns),
            "model_path": model_path
        }
        
        metadata_path = os.path.join(output_dir, "retrain_metadata.json")
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        logger.info(f"Model retrained successfully. Saved to {model_path}")
        return f"Retrained model saved to {model_path} with test accuracy: {test_score:.4f}"
        
    except Exception as e:
        error_msg = f"Retraining failed: {str(e)}"
        logger.error(error_msg)
        return error_msg


class AutonomousMonitoringSystem:
    """
    Fully autonomous monitoring system integrated into the TorinAI architecture.
    Handles drift detection, alerting, and automated responses.
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.is_running = False
        self.monitoring_tasks = []
        self.alert_callbacks: List[Callable] = []
        self.auto_responses = {
            'warn': self._handle_warning,
            'fail': self._handle_failure
        }
        
        # Configuration
        self.check_interval = self.config.get('check_interval', 300)  # 5 minutes
        self.data_sources = self.config.get('data_sources', [])
        self.thresholds = self.config.get('thresholds', {
            'psi_warn': 0.15,
            'psi_fail': 0.4,
            'share_warn': 0.3,
            'share_fail': 0.7
        })
        
        logger.info("Autonomous Monitoring System initialized")
    
    async def start_monitoring(self):
        """Start autonomous monitoring"""
        if self.is_running:
            logger.warning("Monitoring already running")
            return
        
        self.is_running = True
        logger.info("Starting autonomous monitoring system")
        
        # Start monitoring tasks for each data source
        for source in self.data_sources:
            task = asyncio.create_task(self._monitor_data_source(source))
            self.monitoring_tasks.append(task)
        
        # Start health check task
        health_task = asyncio.create_task(self._health_check_loop())
        self.monitoring_tasks.append(health_task)
        
        logger.info(f"Started {len(self.monitoring_tasks)} monitoring tasks")
    
    async def stop_monitoring(self):
        """Stop autonomous monitoring"""
        if not self.is_running:
            return
        
        self.is_running = False
        logger.info("Stopping autonomous monitoring system")
        
        # Cancel all monitoring tasks
        for task in self.monitoring_tasks:
            task.cancel()
        
        # Wait for tasks to complete
        await asyncio.gather(*self.monitoring_tasks, return_exceptions=True)
        self.monitoring_tasks.clear()
        
        logger.info("Autonomous monitoring stopped")
    
    async def _monitor_data_source(self, source: Dict[str, Any]):
        """Monitor a specific data source continuously"""
        source_id = source.get('id', 'unknown')
        
        while self.is_running:
            try:
                logger.debug(f"Checking data source: {source_id}")
                
                # Load reference and current data
                reference_path = source.get('reference_csv')
                current_path = source.get('current_csv')
                
                if not reference_path or not current_path:
                    logger.warning(f"Missing data paths for source {source_id}")
                    await asyncio.sleep(self.check_interval)
                    continue
                
                # Check if current data exists and is recent
                if not os.path.exists(current_path):
                    logger.warning(f"Current data not found: {current_path}")
                    await asyncio.sleep(self.check_interval)
                    continue
                
                # Run drift detection
                result = await self._run_drift_detection(source)
                
                # Handle results
                if result['status'] in ['warn', 'fail']:
                    await self._handle_drift_detection(source_id, result)
                
                # Wait before next check
                await asyncio.sleep(self.check_interval)
                
            except Exception as e:
                logger.error(f"Error monitoring source {source_id}: {e}")
                await asyncio.sleep(self.check_interval)
    
    async def _run_drift_detection(self, source: Dict[str, Any]) -> Dict[str, Any]:
        """Run drift detection for a data source"""
        try:
            # Load data
            reference = load_csv(source['reference_csv'])
            current = load_csv(source['current_csv'])
            
            # Create schema
            schema = Schema(
                datetime_column=source.get('datetime_column'),
                target_column=source.get('target_column'),
                prediction_column=source.get('prediction_column'),
                categorical_features=source.get('categorical_features', []),
                numerical_features=source.get('numerical_features', [])
            )
            
            # Run drift report
            output_dir = source.get('output_dir', 'monitoring_output')
            model_id = source.get('model_id', 'unknown')
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            drift_result = run_drift_report(
                reference=reference,
                current=current,
                schema=schema,
                output_dir=output_dir,
                report_html=f"drift_report_{model_id}_{timestamp}.html",
                report_json=f"drift_report_{model_id}_{timestamp}.json"
            )
            
            # Summarize and evaluate
            summary = summarize_drift(drift_result)
            evaluation = evaluate_thresholds(
                summary,
                self.thresholds['psi_warn'],
                self.thresholds['psi_fail'],
                self.thresholds['share_warn'],
                self.thresholds['share_fail']
            )
            
            return {
                'source': source,
                'summary': summary,
                'evaluation': evaluation,
                'status': evaluation['status'],
                'timestamp': timestamp
            }
            
        except Exception as e:
            logger.error(f"Drift detection failed: {e}")
            return {
                'source': source,
                'status': 'error',
                'error': str(e),
                'timestamp': datetime.now().strftime('%Y%m%d_%H%M%S')
            }
    
    async def _handle_drift_detection(self, source_id: str, result: Dict[str, Any]):
        """Handle drift detection results"""
        status = result['status']
        logger.warning(f"Drift detected in {source_id}: {status}")
        
        # Write alert
        output_dir = result['source'].get('output_dir', 'monitoring_output')
        alert_path = write_alert(
            output_dir=output_dir,
            filename=f"alert_{source_id}_{result['timestamp']}.txt",
            status=status,
            details=result['evaluation']
        )
        
        # Trigger alert callbacks
        for callback in self.alert_callbacks:
            try:
                await callback(source_id, result)
            except Exception as e:
                logger.error(f"Alert callback failed: {e}")
        
        # Execute autonomous response
        if status in self.auto_responses:
            await self.auto_responses[status](source_id, result)
    
    async def _handle_warning(self, source_id: str, result: Dict[str, Any]):
        """Handle warning level drift"""
        logger.info(f"Handling warning for {source_id}")
        
        # Increase monitoring frequency temporarily
        # Send notifications
        # Log detailed analysis
        
    async def _handle_failure(self, source_id: str, result: Dict[str, Any]):
        """Handle failure level drift"""
        logger.critical(f"Handling failure for {source_id}")
        
        # Trigger model retraining
        source = result['source']
        current_csv = source.get('current_csv')
        output_dir = source.get('output_dir', 'monitoring_output')
        
        if current_csv:
            logger.info(f"Triggering automatic retraining for {source_id}")
            retrain_result = retrain_model(current_csv, output_dir)
            logger.info(f"Retraining result: {retrain_result}")
        
        # Send critical alerts
        # Potentially pause model serving
        
    async def _health_check_loop(self):
        """Continuous health checking of the monitoring system"""
        while self.is_running:
            try:
                # Check system health
                await self._check_system_health()
                await asyncio.sleep(60)  # Check every minute
            except Exception as e:
                logger.error(f"Health check failed: {e}")
                await asyncio.sleep(60)
    
    async def _check_system_health(self):
        """Check health of monitoring components"""
        # Check if data sources are accessible
        # Check if output directories are writable
        # Check system resources
        # Validate monitoring configuration
        pass
    
    def add_alert_callback(self, callback: Callable):
        """Add a callback for drift alerts"""
        self.alert_callbacks.append(callback)
    
    def remove_alert_callback(self, callback: Callable):
        """Remove an alert callback"""
        if callback in self.alert_callbacks:
            self.alert_callbacks.remove(callback)
    
    async def trigger_manual_check(self, source_id: Optional[str] = None):
        """Manually trigger a drift check"""
        if source_id:
            # Check specific source
            source = next((s for s in self.data_sources if s.get('id') == source_id), None)
            if source:
                return await self._run_drift_detection(source)
            else:
                raise ValueError(f"Source {source_id} not found")
        else:
            # Check all sources
            results = []
            for source in self.data_sources:
                result = await self._run_drift_detection(source)
                results.append(result)
            return results
    
    def get_monitoring_status(self) -> Dict[str, Any]:
        """Get current monitoring system status"""
        return {
            'is_running': self.is_running,
            'active_tasks': len(self.monitoring_tasks),
            'data_sources': len(self.data_sources),
            'alert_callbacks': len(self.alert_callbacks),
            'config': self.config
        }


# Factory function for creating monitoring system
def create_autonomous_monitoring_system(config: Optional[Dict[str, Any]] = None) -> AutonomousMonitoringSystem:
    """Create and configure autonomous monitoring system"""
    return AutonomousMonitoringSystem(config=config)
