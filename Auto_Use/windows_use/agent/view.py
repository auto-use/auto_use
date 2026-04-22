# Copyright 2026 Autouse AI — https://github.com/auto-use/Auto-Use
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# If you build on this project, please keep this header and credit
# Autouse AI (https://github.com/auto-use/Auto-Use) in forks and derivative works.
# A small attribution goes a long way toward a healthy open-source
# community — thank you for contributing.

import json
import re
import os
import time
from pathlib import Path

class AgentResponseFormatter:
    """Formats agent JSON responses for terminal display"""
    
    FIELD_EMOJIS = {
        "thinking": "🧠 Thinking",
        "verdict_last_action": "📝 Verdict Last Action", 
        "decision": "👁️ Decision",
        "current_goal": "🎯 Current Goal",
        "memory": "💾 Memory",
        "action": "⚡ Action"
    }
    
    @staticmethod
    def _parse_xml_tags(raw_response: str) -> dict | None:
        """
        Parse XML-tag format responses like <thinking>...</thinking>
        Returns dict if successful, None if not XML format.
        """
        # Check if response contains XML-style tags
        if not re.search(r'<(thinking|verdict_last_action|decision|current_goal|memory|action)>', raw_response):
            return None
        
        json_data = {}
        
        # Simple fields - extract content between tags
        simple_fields = ["thinking", "verdict_last_action", "decision", "current_goal", "memory"]
        for field in simple_fields:
            match = re.search(rf'<{field}>(.*?)</{field}>', raw_response, re.DOTALL)
            if match:
                json_data[field] = match.group(1).strip()
        
        # Action field - contains JSON-like content that needs wrapping
        action_match = re.search(r'<action>(.*?)</action>', raw_response, re.DOTALL)
        if action_match:
            action_content = action_match.group(1).strip()
            
            # Remove trailing ``` if present (malformed markdown)
            action_content = re.sub(r'```\s*$', '', action_content).strip()
            
            # Try to parse action content as JSON
            try:
                # If it's already valid JSON
                json_data["action"] = json.loads(action_content)
            except json.JSONDecodeError:
                # Wrap in braces if it looks like JSON properties without outer braces
                if action_content and not action_content.startswith('{'):
                    try:
                        wrapped = '{' + action_content + '}'
                        json_data["action"] = json.loads(wrapped)
                    except json.JSONDecodeError:
                        # Last resort: store as raw string in a wrapper
                        json_data["action"] = {"raw": action_content}
                else:
                    json_data["action"] = {"raw": action_content}
        
        # Return data only if we found at least some fields
        if json_data:
            return json_data
        return None
    
    @staticmethod
    def normalize_response(raw_response: str) -> tuple:
        """
        Normalize LLM response to ensure consistent format.
        Returns tuple: (success: bool, normalized_json: str, raw_response: str)
        
        - success: True if JSON was parsed successfully, False otherwise
        - normalized_json: The normalized JSON string in ```json\n{...}\n``` format
        - raw_response: Original raw response (useful for retry on failure)
        
        Handles multiple formats including:
        - Standard ```json ... ``` blocks
        - Reasoning/thinking text followed by JSON at the end
        - Raw JSON
        - XML-tag format
        """
        try:
            # First, try to extract JSON from various possible formats
            json_data = None
            
            # Case 1: Response has ```json ... ``` format (find the LAST one for reasoning models)
            # Reasoning models often output thinking first, then JSON at the end
            if not json_data:
                try:
                    # Find ALL ```json blocks and use the last one (most likely the actual output)
                    all_json_blocks = list(re.finditer(r'```json\s*(.*?)\s*```', raw_response, re.DOTALL))
                    if all_json_blocks:
                        # Try the last block first (reasoning models put output at end)
                        for match in reversed(all_json_blocks):
                            try:
                                json_str = match.group(1).strip()
                                json_data = json.loads(json_str)
                                break  # Success, stop trying
                            except json.JSONDecodeError:
                                continue  # Try the previous block
                except Exception:
                    pass  # Fall through to next case
            
            # Case 2: Response is raw JSON (no markdown wrapper)
            if not json_data:
                try:
                    # Try to parse the entire response as JSON
                    json_data = json.loads(raw_response.strip())
                except json.JSONDecodeError:
                    pass  # Fall through to next case
            
            # Case 3: Find JSON object using regex (handles embedded JSON)
            if not json_data:
                try:
                    # Find JSON-like structures - use findall to get all matches, try from the end
                    json_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
                    matches = list(re.finditer(json_pattern, raw_response, re.DOTALL))
                    for match in reversed(matches):
                        try:
                            json_str = match.group(0)
                            json_data = json.loads(json_str)
                            break
                        except json.JSONDecodeError:
                            continue
                except Exception:
                    pass
            
            # Case 4: Response has JSON but with extra text - use brace counting
            if not json_data:
                try:
                    # Look for JSON-like structure more aggressively
                    # Find the LAST opening brace to handle reasoning + JSON at end
                    lines = raw_response.split('\n')
                    
                    # Find all potential JSON start positions (lines with '{')
                    potential_starts = [i for i, line in enumerate(lines) if '{' in line]
                    
                    # Try from the last potential start (reasoning models put JSON at end)
                    for json_start in reversed(potential_starts):
                        brace_count = 0
                        json_end = -1
                        
                        for i in range(json_start, len(lines)):
                            brace_count += lines[i].count('{') - lines[i].count('}')
                            if brace_count == 0 and i > json_start:
                                json_end = i
                                break
                        
                        if json_end != -1:
                            # Extract JSON, handling case where { is mid-line
                            first_line = lines[json_start]
                            brace_pos = first_line.find('{')
                            lines[json_start] = first_line[brace_pos:]
                            
                            json_str = '\n'.join(lines[json_start:json_end + 1])
                            try:
                                json_data = json.loads(json_str)
                                break  # Success
                            except json.JSONDecodeError:
                                continue  # Try previous potential start
                except Exception:
                    pass
            
            # Case 5: Response is in XML-tag format (e.g., <thinking>...</thinking>)
            if not json_data:
                json_data = AgentResponseFormatter._parse_xml_tags(raw_response)
            
            # If we couldn't parse JSON, return failure with raw response
            if not json_data:
                return (False, None, raw_response)
            
            # Ensure all required fields are present (NEW FORMAT)
            required_fields = ["thinking", "verdict_last_action", "decision",
                             "current_goal", "memory", "action"]
            
            for field in required_fields:
                if field not in json_data:
                    json_data[field] = "" if field != "action" else []
            
            # Return clean JSON string (no markdown wrapper - avoids backtick collision)
            normalized_json = json.dumps(json_data, indent=2, ensure_ascii=False)
            return (True, normalized_json, raw_response)
            
        except Exception as e:
            # If any error occurs, return failure with raw response
            return (False, None, raw_response)
    
    @staticmethod
    def format_response(normalized_response: str, include_action: bool = False) -> str:
        """Format normalized JSON response into readable terminal output with emojis.
        include_action: If True, include the action block (for terminal). If False, omit it (for frontend stream).
        """
        try:
            # Parse clean JSON string directly (no markdown wrapper)
            data = json.loads(normalized_response)
            
            # Build formatted output
            lines = []
            for field, emoji_label in AgentResponseFormatter.FIELD_EMOJIS.items():
                if field in data:
                    value = data[field]
                    
                    # Skip action field unless include_action (frontend should not stream action)
                    if field == "action" and not include_action:
                        continue
                    
                    # Convert dict/list to string for other fields
                    if isinstance(value, (dict, list)):
                        value = json.dumps(value, indent=2)
                    lines.append(f"- {emoji_label}: {value}")
            
            return "\n".join(lines)
            
        except Exception:
            # If any error, return original response
            return normalized_response