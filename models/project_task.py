import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)

class ProjectTask(models.Model):
    _inherit = 'project.task'

    def _is_task_completed(self, task):
        # Check if a task is completed based on state field or stage name keywords
        if hasattr(task, 'state') and task.state:
            state_completion_keywords = ['done', 'completed', 'finished', 'closed', 'resolved']
            state_lower = str(task.state).lower()
            for keyword in state_completion_keywords:
                if keyword in state_lower:
                    return True
        if task.stage_id and task.stage_id.name:
            stage_name = task.stage_id.name.lower()
            completion_keywords = ['done']
            return any(keyword in stage_name for keyword in completion_keywords)
        return False

    def _move_to_next_stage_if_subtasks_done(self, task_id):
        # Move task to next stage if all subtasks are completed (one stage at a time)
        try:
            task = self.browse(task_id)
            if not task.exists() or not task.child_ids:
                return False
            _logger.info(f"Checking parent task '{task.name}' with {len(task.child_ids)} subtasks")
            incomplete_subtasks = task.child_ids.filtered(lambda t: not self._is_task_completed(t))
            if incomplete_subtasks:
                _logger.info(f"Not all subtasks completed. Remaining: {len(incomplete_subtasks)}")
                return False
            _logger.info(f"All subtasks completed for '{task.name}'. Moving to next stage...")
            current_stage = task.stage_id
            project = task.project_id
            if not (project and current_stage):
                _logger.warning("No project or current stage found")
                return False
            project_stages = self.env['project.task.type'].search([
                ('project_ids', 'in', [project.id])
            ], order='sequence')
            current_index = None
            for idx, stage in enumerate(project_stages):
                if stage.id == current_stage.id:
                    current_index = idx
                    break
            if current_index is not None and current_index < len(project_stages) - 1:
                next_stage = project_stages[current_index + 1]
                task.write({'stage_id': next_stage.id})
                task.message_post(
                    body=f"Task automatically moved to '{next_stage.name}' stage because all subtasks are completed.",
                    message_type='notification')
                _logger.info(f"SUCCESS: Task '{task.name}' moved to stage '{next_stage.name}'")
                return True
            else:
                _logger.info("No next stage available or already at last stage")
        except Exception as e:
            _logger.error(f"Error moving task {task_id} to next stage: {str(e)}")
        return False
    def _check_parent_chain_recursively(self, task):
        # Recursively check parent tasks up the hierarchy
        if not task.parent_id:
            return
        _logger.info(f"Checking parent task '{task.parent_id.name}' due to subtask '{task.name}' change")
        moved = self._move_to_next_stage_if_subtasks_done(task.parent_id.id)
        if moved and task.parent_id.parent_id:
            self._check_parent_chain_recursively(task.parent_id)
    def write(self, vals):
        # Override write to trigger automation when subtasks change stage/state
        result = super(ProjectTask, self).write(vals)
        if 'stage_id' in vals or 'state' in vals:
            for task in self:
                if task.parent_id:
                    _logger.info(f"Subtask '{task.name}' updated, checking parent '{task.parent_id.name}'")
                    moved = self._move_to_next_stage_if_subtasks_done(task.parent_id.id)
                    if moved and task.parent_id.parent_id:
                        self._check_parent_chain_recursively(task.parent_id)
        return result
    def unlink(self):
        # Check parent tasks when subtasks are deleted
        parent_tasks = self.mapped('parent_id').filtered(lambda x: x)
        result = super(ProjectTask, self).unlink()
        for parent in parent_tasks:
            if parent.exists():
                self._move_to_next_stage_if_subtasks_done(parent.id)
                if parent.parent_id:
                    self._check_parent_chain_recursively(parent)
        return result

    @api.model
    def debug_check_task(self, task_id):
        # Debug method to manually check a specific task
        _logger.info(f"=== DEBUG: Manually checking task {task_id} ===")
        result = self._move_to_next_stage_if_subtasks_done(task_id)
        _logger.info(f"=== DEBUG: Result: {result} ===")
        return result