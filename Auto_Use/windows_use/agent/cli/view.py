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
import time
from pathlib import Path


class CLIAgentResponseFormatter:
    """Validates and normalizes CLI agent JSON responses before they enter agent memory"""
    
    # Required fields for CLI agent schema
    REQUIRED_FIELDS = ["thinking", "current_goal", "memory", "action"]
    
    @staticmethod
    def _extract_json(raw_response: str) -> dict | None:
        """
        Extract JSON from various LLM output formats.
        Returns parsed dict if successful, None otherwise.
        """
        # Case 1: Find ```json blocks (use LAST one for reasoning models)
        json_blocks = list(re.finditer(r'```json\s*(.*?)\s*```', raw_response, re.DOTALL))
        if json_blocks:
            for match in reversed(json_blocks):
                try:
                    return json.loads(match.group(1).strip())
                except json.JSONDecodeError:
                    continue
        
        # Case 2: Raw JSON (entire response)
        try:
            return json.loads(raw_response.strip())
        except json.JSONDecodeError:
            pass
        
        # Case 3: Find JSON object using brace matching (last occurrence)
        try:
            lines = raw_response.split('\n')
            potential_starts = [i for i, line in enumerate(lines) if '{' in line]
            
            for json_start in reversed(potential_starts):
                brace_count = 0
                json_end = -1
                
                for i in range(json_start, len(lines)):
                    brace_count += lines[i].count('{') - lines[i].count('}')
                    if brace_count == 0 and i > json_start:
                        json_end = i
                        break
                
                if json_end != -1:
                    first_line = lines[json_start]
                    brace_pos = first_line.find('{')
                    lines[json_start] = first_line[brace_pos:]
                    
                    json_str = '\n'.join(lines[json_start:json_end + 1])
                    try:
                        return json.loads(json_str)
                    except json.JSONDecodeError:
                        continue
        except:
            pass
        
        return None
    
    @staticmethod
    def _validate_schema(json_data: dict) -> tuple:
        """
        Validate that all required fields exist and are properly typed.
        Returns (is_valid, missing_fields)
        """
        missing_fields = []
        
        for field in CLIAgentResponseFormatter.REQUIRED_FIELDS:
            if field not in json_data:
                missing_fields.append(field)
            elif field == "action" and not isinstance(json_data[field], list):
                missing_fields.append(f"{field} (must be array)")
            elif field != "action" and not isinstance(json_data[field], str):
                missing_fields.append(f"{field} (must be string)")
        
        return (len(missing_fields) == 0, missing_fields)
    
    @staticmethod
    def normalize_response(raw_response: str) -> tuple:
        """
        Normalize and validate LLM response.
        
        Returns:
            tuple: (success, normalized_json, raw_response)
            - success: True if valid and complete, False otherwise
            - normalized_json: Formatted JSON string or None if failed
            - raw_response: Original response (for retry on failure)
        """
        # Step 1: Extract JSON
        json_data = CLIAgentResponseFormatter._extract_json(raw_response)
        
        if json_data is None:
            # Raw response already saved by service._save_raw_response before this call
            return (False, None, raw_response)
        
        # Step 2: Validate schema (strict - all fields must exist)
        is_valid, missing_fields = CLIAgentResponseFormatter._validate_schema(json_data)
        
        if not is_valid:
            # Raw response already saved by service._save_raw_response before this call
            return (False, None, raw_response)
        
        # Step 3: Normalize and format (no markdown wrapper - avoids backtick collision)
        normalized_json = json.dumps(json_data, indent=2, ensure_ascii=False)
        return (True, normalized_json, raw_response)
    
    @staticmethod
    def get_action_block(normalized_response: str) -> list:
        """
        Extract action block from validated response.
        Call this only after normalize_response returns success.
        
        Returns:
            list: Action array from the response
        """
        try:
            json_data = json.loads(normalized_response)
            return json_data.get("action", [])
        except:
            pass
        return []