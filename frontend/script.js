document.addEventListener('DOMContentLoaded', () => {
    // Splash screen: pick the per-OS animation at runtime so a single checkout
    // works on both macOS and Windows without any build-time file patching.
    // Each animation HTML posts 'splashDone' back to us when finished.
    const splash = document.getElementById('splashOverlay');
    if (splash) {
        const splashFrame = document.getElementById('splashFrame');
        if (splashFrame && !splashFrame.src) {
            const ua = navigator.userAgent || '';
            const plat = navigator.platform || '';
            const isMac = /Mac/i.test(plat) || /Mac OS X/i.test(ua);
            splashFrame.src = isMac ? 'mac_animation.html' : 'windows_animation.html';
        }
        window.addEventListener('message', (e) => {
            if (e.data === 'splashDone') {
                splash.style.pointerEvents = 'none';
                splash.classList.add('fade-out');
                splash.addEventListener('transitionend', () => splash.remove());
            }
        });
    }

    const llmWrapper = document.getElementById('llmWrapper');
    const currentSelection = llmWrapper.querySelector('.current-selection');
    const selectionText = currentSelection.querySelector('.selection-text');
    const dropdownOptions = document.getElementById('dropdownOptions');

    // API Key Management - existence flags only (true/null), never actual keys
    const apiKeys = {
        openrouter: null,
        groq: null,
        openai: null,
        anthropic: null,
        perplexity: null
    };


    // 1. Click to toggle the dropdown list
    llmWrapper.addEventListener('click', () => {
        if (llmWrapper.classList.contains('expanded')) {
            // Collapse: Reset height to initial (let CSS transition handle it)
            llmWrapper.style.height = '';
            llmWrapper.classList.remove('expanded');
            dropdownOptions.querySelectorAll('.active-provider').forEach(el => el.classList.remove('active-provider'));
        } else {
            // Expand: measure the wrapper's children directly so the height
            // adapts to whatever the current header looks like (including the
            // taller "selected model + brain icon" state after the first
            // selection). Using offsetHeight of the two children skips the
            // wrapper's own padding, which `box-sizing: content-box` adds back
            // on top of any inline `height` we set — that mismatch was the
            // empty-space bug on the second open.
            llmWrapper.classList.add('expanded');
            const headerEl = llmWrapper.querySelector('.glass-button-content');
            const headerH  = headerEl ? headerEl.offsetHeight : 0;
            const optionsH = dropdownOptions.offsetHeight;
            llmWrapper.style.height = `${headerH + optionsH}px`;
        }
    });

    // 2. Close dropdown when clicking outside
    document.addEventListener('click', (e) => {
        if (!llmWrapper.contains(e.target) && llmWrapper.classList.contains('expanded')) {
            llmWrapper.style.height = '';
            llmWrapper.classList.remove('expanded');
            dropdownOptions.querySelectorAll('.active-provider').forEach(el => el.classList.remove('active-provider'));
        }
    });

    // Store selected provider and model
    let selectedProvider = null;
    let selectedModel = null;

    // Function to complete model selection (after API key is confirmed)
    const completeModelSelection = (option, providerName, modelId) => {
        // Get the model name (text content without the icon)
        const modelName = option.cloneNode(true);
        const iconSvg = modelName.querySelector('.model-icon');
        
        // Extract just the text
        let modelText = modelName.textContent.trim();
        
        // Store the selection
        selectedProvider = providerName;
        selectedModel = modelId;
        
        // Clear current selection and add new content
        currentSelection.innerHTML = '';
        
        // Add the model name text
        const textSpan = document.createElement('span');
        textSpan.className = 'selection-text';
        textSpan.textContent = modelText;
        currentSelection.appendChild(textSpan);
        
        // If the original option had an icon, add it to the selection
        if (iconSvg) {
            const iconClone = iconSvg.cloneNode(true);
            iconClone.classList.add('selection-icon');
            currentSelection.appendChild(iconClone);
        }

        // Input stays locked — handleModelSelection controls unlock based on key status
        // (do not enable here)

        // Close the dropdown
        llmWrapper.style.height = '';
        llmWrapper.classList.remove('expanded');
        
        console.log(`Selected: ${selectedProvider} / ${selectedModel}`);
    };

    // Function to handle model selection (checks for API key first)
    const handleModelSelection = (option, providerName) => {
        const modelId = option.dataset.modelId;
        
        // Always complete model selection (update UI, store selection)
        completeModelSelection(option, providerName, modelId);
        
        // Vertex models — check vertex config instead of API key
        const isVertex = modelId && modelId.includes('vertex');
        if (isVertex) {
            fetch('/api/vertex/status')
                .then(res => res.json())
                .then(data => {
                    if (data.project_id) {
                        chatInput.disabled = false;
                        chatInput.placeholder = 'Type your task...';
                    } else {
                        chatInput.disabled = true;
                        chatInput.placeholder = 'Configure GCP Vertex in Settings first...';
                        if (settingsOverlay) {
                            loadKeyStatus();
                            showSettingsView('apikeys');
                            settingsOverlay.classList.add('active');
                        }
                    }
                })
                .catch(err => console.error('Failed to check vertex status:', err));
            return;
        }
        
        // Then check if key exists
        fetch('/api/keys/status')
            .then(res => res.json())
            .then(status => {
                if (status[providerName]) {
                    // Key exists — unlock input
                    chatInput.disabled = false;
                    chatInput.placeholder = 'Type your task...';
                } else {
                    // No key — keep input locked, open settings
                    chatInput.disabled = true;
                    chatInput.placeholder = 'Add API key in Settings first...';
                    if (settingsOverlay) {
                        loadKeyStatus();
                        showSettingsView('apikeys');
                        settingsOverlay.classList.add('active');
                    }
                }
            })
            .catch(err => {
                console.error('Failed to check key status:', err);
            });
    };

    // Function to render providers and models
    const renderProviders = (providers) => {
        dropdownOptions.innerHTML = '';

        if (!providers || providers.length === 0) {
            const errorDiv = document.createElement('div');
            errorDiv.className = 'provider-item';
            errorDiv.innerHTML = '<span>No providers found</span>';
            dropdownOptions.appendChild(errorDiv);
            return;
        }

        providers.forEach(provider => {
            const providerItem = document.createElement('div');
            providerItem.className = 'provider-item';

            const providerNameSpan = document.createElement('span');
            providerNameSpan.textContent = provider.name;
            providerItem.appendChild(providerNameSpan);

            // Show sub-menu on hover, keep last hovered one visible
            providerItem.addEventListener('mouseenter', () => {
                dropdownOptions.querySelectorAll('.provider-item.active-provider').forEach(el => {
                    el.classList.remove('active-provider');
                });
                providerItem.classList.add('active-provider');
            });

            const subMenu = document.createElement('div');
            subMenu.className = 'sub-menu';

            const subMenuCard = document.createElement('div');
            subMenuCard.className = 'sub-menu-card';

            // Add glass effects
            subMenuCard.innerHTML = `
                <div class="liquidGlass-effect-btn"></div>
                <div class="liquidGlass-tint-btn"></div>
                <div class="liquidGlass-shine-btn"></div>
            `;

            const subMenuContent = document.createElement('div');
            subMenuContent.className = 'sub-menu-content';

            provider.models.forEach(model => {
                const modelOption = document.createElement('div');
                modelOption.className = 'model-option';
                modelOption.dataset.modelId = model.id; // Store ID for backend use

                const modelNameText = document.createTextNode(model.display_name);
                modelOption.appendChild(modelNameText);

                if (model.reasoning_support) {
                    const svgIcon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
                    svgIcon.classList.add('model-icon');
                    const useElement = document.createElementNS("http://www.w3.org/2000/svg", "use");
                    useElement.setAttribute('href', '#icon-brain');
                    svgIcon.appendChild(useElement);
                    modelOption.appendChild(svgIcon);
                }

                // Add click listener
                modelOption.addEventListener('click', (e) => {
                    e.stopPropagation(); // Prevent wrapper toggle
                    handleModelSelection(modelOption, provider.id);
                });

                subMenuContent.appendChild(modelOption);
            });

            subMenuCard.appendChild(subMenuContent);
            subMenu.appendChild(subMenuCard);
            providerItem.appendChild(subMenu);
            dropdownOptions.appendChild(providerItem);
        });
    };

    // Initialize fetching data
    const loadData = () => {
        fetch('/api/providers')
            .then(response => response.json())
            .then(providers => {
                renderProviders(providers);
            })
            .catch(err => {
                console.error("Failed to load providers:", err);
                renderProviders([]);
            });
    };

    // Position settings button dynamically next to LLM button
    const settingsBtnEl = document.getElementById('settingsBtn');
    const positionSettingsBtn = () => {
        if (!settingsBtnEl || !llmWrapper) return;
        const rect = llmWrapper.getBoundingClientRect();
        settingsBtnEl.style.left = (rect.right + 10) + 'px';
    };

    // Reposition on load, resize, and after any selection change
    positionSettingsBtn();
    window.addEventListener('resize', positionSettingsBtn);

    // Observe LLM button size/position changes (e.g. after model selection or layout switch)
    const resizeObserver = new ResizeObserver(positionSettingsBtn);
    resizeObserver.observe(llmWrapper);

    // While the LLM wrapper's `left` is animating (chat box slide-in/out),
    // re-read its position every frame so the settings cog tracks it
    // smoothly. Without this rAF loop the cog only moves on transitionend
    // and visibly snaps at the end of the 0.5s slide.
    let _settingsTrackRAF = 0;
    const trackSettingsBtnPosition = () => {
        const tick = () => {
            positionSettingsBtn();
            _settingsTrackRAF = requestAnimationFrame(tick);
        };
        if (!_settingsTrackRAF) _settingsTrackRAF = requestAnimationFrame(tick);
    };
    const stopTrackingSettingsBtn = () => {
        if (_settingsTrackRAF) {
            cancelAnimationFrame(_settingsTrackRAF);
            _settingsTrackRAF = 0;
        }
        positionSettingsBtn();
    };

    const isLeftTransition = (e) => e.propertyName === 'left' && e.target === llmWrapper;
    llmWrapper.addEventListener('transitionrun',    (e) => { if (isLeftTransition(e)) trackSettingsBtnPosition();   });
    llmWrapper.addEventListener('transitionstart',  (e) => { if (isLeftTransition(e)) trackSettingsBtnPosition();   });
    llmWrapper.addEventListener('transitionend',    (e) => { if (isLeftTransition(e)) stopTrackingSettingsBtn();    });
    llmWrapper.addEventListener('transitioncancel', (e) => { if (isLeftTransition(e)) stopTrackingSettingsBtn();    });

    // Load immediately
    loadData();

    // Load API key status on startup
    fetch('/api/keys/status')
        .then(res => res.json())
        .then(status => {
            Object.keys(status).forEach(provider => {
                apiKeys[provider] = status[provider] ? true : null;
            });
        })
        .catch(err => console.error('Failed to load key status:', err));

    // ============================================
    // SETTINGS PANEL - Open / Close
    // ============================================
    const settingsBtn = document.getElementById('settingsBtn');
    const settingsOverlay = document.getElementById('settingsOverlay');
    const settingsSaveBtn = document.getElementById('settingsSaveBtn');
    const settingsMenuView = document.getElementById('settingsMenuView');
    const settingsApikeysView = document.getElementById('settingsApikeysView');
    const settingsRemoteView = document.getElementById('settingsRemoteView');

    // Helper: seal a provider row (key exists)
    const sealProviderRow = (row) => {
        const input = row.querySelector('.settings-provider-input');
        const deleteBtn = row.querySelector('.settings-delete-btn');
        input.value = '';
        input.placeholder = 'API Key already exists';
        input.disabled = true;
        deleteBtn.style.display = 'flex';
    };

    // Helper: unseal a provider row (no key)
    const unsealProviderRow = (row) => {
        const input = row.querySelector('.settings-provider-input');
        const deleteBtn = row.querySelector('.settings-delete-btn');
        const provider = row.dataset.provider;
        const placeholders = { openrouter: 'sk-or-...', groq: 'gsk_...', openai: 'sk-...', anthropic: 'sk-ant-...', google: 'AIza...' };
        input.value = '';
        input.placeholder = placeholders[provider] || 'Enter API key...';
        input.disabled = false;
        deleteBtn.style.display = 'none';
    };

    // Load key status from backend
    const loadKeyStatus = () => {
        fetch('/api/keys/status')
            .then(res => res.json())
            .then(status => {
                document.querySelectorAll('.settings-provider-row').forEach(row => {
                    const provider = row.dataset.provider;
                    if (status[provider]) {
                        sealProviderRow(row);
                    } else {
                        unsealProviderRow(row);
                    }
                });
                // If Google has no API key, check if Vertex is configured instead
                if (!status['google']) {
                    fetch('/api/vertex/status')
                        .then(res => res.json())
                        .then(data => {
                            if (data.project_id) {
                                const googleRow = document.querySelector('.settings-provider-row[data-provider="google"]');
                                if (googleRow) {
                                    sealProviderRow(googleRow);
                                    const input = googleRow.querySelector('.settings-provider-input');
                                    if (input) input.placeholder = 'Vertex AI configured';
                                }
                            }
                        })
                        .catch(() => {});
                }
            })
            .catch(err => console.error('Failed to load key status:', err));
    };

    // Delete button handlers
    document.querySelectorAll('.settings-delete-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const row = btn.closest('.settings-provider-row');
            const provider = row.dataset.provider;

            fetch('/api/keys/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ provider })
            })
            .then(res => res.json())
            .then(() => {
                unsealProviderRow(row);
                // Clear in-memory flag
                apiKeys[provider] = null;
                // Lock input and reset if deleted key belongs to the active provider
                if (provider === selectedProvider) {
                    chatInput.disabled = true;
                    chatInput.value = '';
                    chatInput.placeholder = 'Select a model to start...';
                    selectedProvider = null;
                    selectedModel = null;
                    // Reset LLM button to default
                    currentSelection.innerHTML = '';
                    const defaultSpan = document.createElement('span');
                    defaultSpan.className = 'selection-text';
                    defaultSpan.textContent = 'LLM Provider';
                    currentSelection.appendChild(defaultSpan);
                }
            })
            .catch(err => console.error('Failed to delete key:', err));
        });
    });

    // ============================================
    // GCP VERTEX AI POPUP
    // ============================================
    const gcpVertexBtn = document.getElementById('gcpVertexBtn');
    const vertexOverlay = document.getElementById('vertexOverlay');
    const vertexDoneBtn = document.getElementById('vertexDoneBtn');
    const vertexProjectId = document.getElementById('vertexProjectId');
    const vertexLocation = document.getElementById('vertexLocation');

    // Location field — muted by default, vivid on edit
    if (vertexLocation) {
        vertexLocation.addEventListener('focus', () => {
            if (vertexLocation.value === 'global') {
                vertexLocation.select();
            }
            vertexLocation.classList.add('edited');
        });
        vertexLocation.addEventListener('blur', () => {
            if (!vertexLocation.value.trim()) {
                vertexLocation.value = 'global';
            }
            if (vertexLocation.value === 'global') {
                vertexLocation.classList.remove('edited');
            }
        });
    }

    // Open vertex popup
    if (gcpVertexBtn && vertexOverlay) {
        gcpVertexBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            // Load existing vertex config
            fetch('/api/vertex/status')
                .then(res => res.json())
                .then(data => {
                    if (data.project_id) vertexProjectId.value = data.project_id;
                    const loc = data.location || 'global';
                    vertexLocation.value = loc;
                    if (loc !== 'global') vertexLocation.classList.add('edited');
                    else vertexLocation.classList.remove('edited');
                })
                .catch(() => {});
            vertexOverlay.classList.add('active');
        });

        // Close on overlay click
        vertexOverlay.addEventListener('click', (e) => {
            if (e.target === vertexOverlay) {
                vertexOverlay.classList.remove('active');
            }
        });
    }

    // Save vertex config
    if (vertexDoneBtn) {
        vertexDoneBtn.addEventListener('click', () => {
            const projectId = vertexProjectId.value.trim();
            if (!projectId) {
                vertexProjectId.style.animation = 'shake 0.4s ease';
                setTimeout(() => vertexProjectId.style.animation = '', 400);
                return;
            }
            const location = vertexLocation.value.trim() || 'global';
            fetch('/api/vertex/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ project_id: projectId, location: location })
            })
            .then(res => res.json())
            .then(() => {
                gcpVertexBtn.classList.add('configured');
                vertexOverlay.classList.remove('active');
                // Unlock chat input if a Vertex model is currently selected
                if (selectedModel && selectedModel.includes('vertex')) {
                    chatInput.disabled = false;
                    chatInput.placeholder = 'Type your task...';
                }
            })
            .catch(err => console.error('Failed to save vertex config:', err));
        });
    }

    // Load vertex status on startup to tint button
    fetch('/api/vertex/status')
        .then(res => res.json())
        .then(data => {
            if (data.project_id && gcpVertexBtn) {
                gcpVertexBtn.classList.add('configured');
            }
        })
        .catch(() => {});

    // Helper: switch settings view
    const showSettingsView = (viewName) => {
        settingsMenuView.classList.remove('active');
        settingsApikeysView.classList.remove('active');
        settingsRemoteView.classList.remove('active');
        if (viewName === 'apikeys') settingsApikeysView.classList.add('active');
        else if (viewName === 'remote') settingsRemoteView.classList.add('active');
        else settingsMenuView.classList.add('active');
    };

    // Helper: reset to menu view when closing
    const resetSettingsToMenu = () => {
        settingsOverlay.classList.remove('active');
        // Reset to menu after transition completes
        setTimeout(() => showSettingsView('menu'), 300);
    };

    if (settingsBtn && settingsOverlay) {
        settingsBtn.addEventListener('click', () => {
            loadKeyStatus();
            showSettingsView('menu');
            settingsOverlay.classList.add('active');
        });

        // Close button on menu view
        document.getElementById('settingsCloseBtn').addEventListener('click', () => {
            resetSettingsToMenu();
        });

        // Menu item navigation
        document.querySelectorAll('.settings-menu-item').forEach(item => {
            item.addEventListener('click', () => {
                const view = item.dataset.view;
                if (view === 'apikeys') {
                    loadKeyStatus();
                    showSettingsView('apikeys');
                } else if (view === 'remote') {
                    showSettingsView('remote');
                    loadRemoteStatus();
                }
            });
        });

        // Back buttons
        document.querySelectorAll('.settings-back-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                showSettingsView('menu');
            });
        });

        // Save button (API Keys)
        settingsSaveBtn.addEventListener('click', () => {
            const savePromises = [];
            document.querySelectorAll('.settings-provider-row').forEach(row => {
                const input = row.querySelector('.settings-provider-input');
                const provider = row.dataset.provider;
                const value = input.value.trim();

                if (!input.disabled && value) {
                    savePromises.push(
                        fetch('/api/keys/save', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ provider, key: value })
                        })
                        .then(res => res.json())
                        .then(() => {
                            sealProviderRow(row);
                            apiKeys[provider] = true;
                        })
                    );
                }
            });

            Promise.all(savePromises)
                .then(() => {
                    resetSettingsToMenu();
                    if (selectedProvider && selectedModel) {
                        const isVertex = selectedModel.includes('vertex');
                        if (isVertex) {
                            fetch('/api/vertex/status')
                                .then(res => res.json())
                                .then(data => {
                                    if (data.project_id) {
                                        chatInput.disabled = false;
                                        chatInput.placeholder = 'Type your task...';
                                    } else {
                                        chatInput.disabled = true;
                                        chatInput.placeholder = 'Configure GCP Vertex in Settings first...';
                                    }
                                })
                                .catch(() => {});
                        } else if (apiKeys[selectedProvider]) {
                            chatInput.disabled = false;
                            chatInput.placeholder = 'Type your task...';
                        }
                    }
                })
                .catch(err => {
                    console.error('Failed to save keys:', err);
                    resetSettingsToMenu();
                });
        });

        // Remote Connection — QR + status logic
        const remoteSetup = document.getElementById('remoteSetup');
        const remoteConnected = document.getElementById('remoteConnected');
        const remoteQrContainer = document.getElementById('remoteQrContainer');
        const remoteBotName = document.getElementById('remoteBotName');
        const remoteDisconnectBtn = document.getElementById('remoteDisconnectBtn');

        function loadRemoteStatus() {
            fetch('/api/telegram/status')
                .then(res => res.json())
                .then(data => {
                    if (data.connected && data.bot_username) {
                        remoteSetup.style.display = 'none';
                        remoteConnected.style.display = 'flex';
                        remoteBotName.textContent = '@' + data.bot_username;
                    } else {
                        remoteSetup.style.display = 'flex';
                        remoteConnected.style.display = 'none';
                        const pairUrl = 'http://' + data.local_ip + ':5000/pair';
                        remoteQrContainer.innerHTML = '';
                        new QRCode(remoteQrContainer, {
                            text: pairUrl,
                            width: 160,
                            height: 160,
                            colorDark: '#ffffff',
                            colorLight: 'transparent',
                            correctLevel: QRCode.CorrectLevel.M
                        });
                    }
                })
                .catch(() => {});
        }

        if (remoteDisconnectBtn) {
            remoteDisconnectBtn.addEventListener('click', () => {
                fetch('/api/telegram/disconnect', { method: 'POST' })
                    .then(() => loadRemoteStatus())
                    .catch(() => {});
            });
        }

        settingsOverlay.addEventListener('click', (e) => {
            if (e.target === settingsOverlay) {
                resetSettingsToMenu();
            }
        });

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && settingsOverlay.classList.contains('active')) {
                resetSettingsToMenu();
            }
        });
    }

    // Function to update the image stream (called from Python)
    window.updateAgentImage = (base64Image) => {
        const imgElement = document.querySelector('.stream-image');
        if (imgElement && base64Image) {
            imgElement.src = `data:image/jpeg;base64,${base64Image}`;
            imgElement.style.display = 'block'; // Show image when data arrives
        }
    };
    
    // Milestone streaming - word by word, stacking vertically
    window.streamMilestone = (text) => {
        const milestoneStream = document.getElementById('milestoneStream');
        if (!milestoneStream) return;
        
        // Create new milestone line
        const milestoneLine = document.createElement('div');
        milestoneLine.className = 'milestone-line';
        milestoneStream.appendChild(milestoneLine);
        
        // Split text into words
        const words = text.split(/\s+/).filter(w => w.length > 0);
        let currentIndex = 0;
        
        // Fast streaming speed (milliseconds per word)
        const speed = 30;
        
        const streamWord = () => {
            if (currentIndex < words.length) {
                // Add word with space
                if (currentIndex > 0) {
                    milestoneLine.textContent += ' ';
                }
                milestoneLine.textContent += words[currentIndex];
                currentIndex++;
                
                // Auto-scroll to bottom
                milestoneStream.parentElement.scrollTop = milestoneStream.parentElement.scrollHeight;
                
                setTimeout(streamWord, speed);
            }
        };
        
        // Start streaming
        streamWord();
    };

    // Word-by-word streaming for agent text in the response strip
    let streamingTimeout = null;
    window.streamAgentText = (text) => {
        const agentText = document.getElementById('agentText');
        const agentStrip = document.getElementById('agentResponseStrip');
        
        if (!agentText || !agentStrip) return;
        
        // Make sure strip is visible
        agentStrip.classList.add('active');
        
        // Clear any existing streaming
        if (streamingTimeout) {
            clearTimeout(streamingTimeout);
        }
        
        // Split text into words
        const words = text.split(/\s+/).filter(w => w.length > 0);
        let currentIndex = 0;
        let currentLine = '';
        
        // Speed in milliseconds per word (fast but readable)
        const baseSpeed = 25;
        
        const streamWord = () => {
            if (currentIndex < words.length) {
                // Add next word to current line
                const testLine = currentLine ? currentLine + ' ' + words[currentIndex] : words[currentIndex];
                
                // Temporarily set to measure width
                agentText.textContent = testLine;
                
                // Check if text overflows the container
                if (agentText.scrollWidth > agentText.clientWidth) {
                    // Reset - start fresh from left with current word
                    currentLine = words[currentIndex];
                    agentText.textContent = currentLine;
                } else {
                    // Fits - keep adding
                    currentLine = testLine;
                }
                
                currentIndex++;
                streamingTimeout = setTimeout(streamWord, baseSpeed);
            }
        };
        
        // Start streaming
        streamWord();
    };


    // 4. Auto-resize Chat Input
    const chatInput = document.querySelector('.chat-input');
    
    if (chatInput) {
        // Function to adjust height
        const adjustHeight = () => {
            // Reset height to auto to get the correct scrollHeight
            chatInput.style.height = 'auto';
            
            // Calculate new height (clamped by CSS max-height)
            const newHeight = Math.min(chatInput.scrollHeight, 150); // 150px matches CSS max-height
            
            // Apply new height, respecting minimum
            chatInput.style.height = `${Math.max(newHeight, 44)}px`; // 44px matches CSS min-height base
        };

        // Event listeners for auto-resize
        chatInput.addEventListener('input', adjustHeight);
        
        // Initial adjustment
        adjustHeight();

        // 5. Handle Enter key to start agent
        chatInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault(); // Prevent default newline
                
                const message = chatInput.value.trim();
                if (message && selectedProvider && selectedModel) {
                    // Show Agent Response Strip
                    const agentStrip = document.getElementById('agentResponseStrip');
                    const agentText = document.getElementById('agentText');
                    // Get the stop button
                    const stopBtn = document.getElementById('stopAgentBtn');
                    
                    if (agentStrip) {
                        agentStrip.classList.add('active');
                        // Disable input
                        chatInput.disabled = true;
                        chatInput.classList.add('agent-active');
                        agentText.textContent = 'Starting agent...';

                        // Show Stop Button
                        if (stopBtn) stopBtn.classList.add('active');

                        // Switch to split layout
                        document.getElementById('imageStreamContainer').classList.add('agent-visible');
                        document.getElementById('chatWrapper').classList.add('split-layout');
                        document.getElementById('llmWrapper').classList.add('split-layout');

                        // Hide eyes only, keep glow
                        const welcomeEl = document.getElementById('welcomeOverlay');
                        if (welcomeEl) welcomeEl.classList.add('eyes-hidden');

                        // Clear milestone stream for fresh start
                        const milestoneStream = document.getElementById('milestoneStream');
                        if (milestoneStream) {
                            milestoneStream.innerHTML = '';
                        }
                    }
                    
                    // Send request to start agent
                    fetch('/api/start-agent', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({
                            provider: selectedProvider,
                            model: selectedModel,
                            task: message
                        })
                    })
                    .then(response => response.json())
                    .then(data => {
                        if (data.status === 'started') {
                            agentText.textContent = 'Agent running...';
                            // Clear input after successful start
                            chatInput.value = '';
                            adjustHeight();
                        } else if (data.error) {
                            agentText.textContent = `Error: ${data.error}`;
                            // Re-enable input on error
                            chatInput.disabled = false;
                            if (stopBtn) stopBtn.classList.remove('active');
                        }
                    })
                    .catch(err => {
                        console.error('Failed to start agent:', err);
                        agentText.textContent = 'Failed to start agent';
                        // Re-enable input on error
                        chatInput.disabled = false;
                        if (stopBtn) stopBtn.classList.remove('active');
                    });
                }
            }
        });
        
        // 6. Handle Stop Button Click
        const stopBtn = document.getElementById('stopAgentBtn');
        if (stopBtn) {
            stopBtn.addEventListener('click', () => {
                // Stop streaming immediately
                if (streamingTimeout) {
                    clearTimeout(streamingTimeout);
                    streamingTimeout = null;
                }

                const agentText = document.getElementById('agentText');
                if (agentText) agentText.textContent = 'Stopping agent...';

                // Pop-vanish the button
                stopBtn.classList.add('pop-vanish');
                setTimeout(() => {
                    stopBtn.classList.remove('active', 'pop-vanish');
                }, 600);

                // Force-close any active tool animations immediately
                if (window.webSearchEnd) window.webSearchEnd();
                if (window.shellEnd) window.shellEnd();

                fetch('/api/stop-agent', { method: 'POST' })
                    .then(res => res.json())
                    .then(data => {
                        console.log('Agent stop requested:', data);
                        const agentStrip = document.getElementById('agentResponseStrip');
                        if (agentStrip) agentStrip.classList.remove('active');

                        // Revert to centered layout
                        document.getElementById('imageStreamContainer').classList.remove('agent-visible');
                        document.getElementById('chatWrapper').classList.remove('split-layout');
                        document.getElementById('llmWrapper').classList.remove('split-layout');

                        chatInput.disabled = false;
                        chatInput.classList.remove('agent-active');
                        chatInput.focus();
                    })
                    .catch(err => console.error('Error stopping agent:', err));
            });
        }
    }
    
    // Agent completion handler (called from Python when agent finishes naturally)
    window.agentComplete = () => {
        const stopBtn = document.getElementById('stopAgentBtn');
        const agentStrip = document.getElementById('agentResponseStrip');
        const chatInput = document.querySelector('.chat-input');
        
        // Clear any streaming
        if (streamingTimeout) {
            clearTimeout(streamingTimeout);
            streamingTimeout = null;
        }
        
        // Hide Stop Button (skip if already gone from click)
        if (stopBtn && stopBtn.classList.contains('active') && !stopBtn.classList.contains('pop-vanish')) {
            stopBtn.classList.add('pop-vanish');
            setTimeout(() => {
                stopBtn.classList.remove('active', 'pop-vanish');
            }, 600);
        }
        
        // Force-close any active tool animations immediately
        if (window.webSearchEnd) window.webSearchEnd();
        if (window.shellEnd) window.shellEnd();

        // Hide Strip
        if (agentStrip) agentStrip.classList.remove('active');

        // Revert to centered layout
        document.getElementById('imageStreamContainer').classList.remove('agent-visible');
        document.getElementById('chatWrapper').classList.remove('split-layout');
        document.getElementById('llmWrapper').classList.remove('split-layout');

        // Enable Input
        if (chatInput) {
            chatInput.disabled = false;
            chatInput.classList.remove('agent-active');
            chatInput.focus();
        }
    };

    // ============================================
    // GLOBE ANIMATION FOR WEB SEARCH
    // ============================================
    
    const mainGlobeContainer = document.getElementById('mainGlobeContainer');
    const imageStreamContainer = document.getElementById('imageStreamContainer');
    
    let globeInitialized = false;
    let globeScene, globeCamera, globeRenderer, globeEarth, globeNetworkGroup;
    let globeParticles, globeLineMesh, globeActivePackets;
    let globeAnimationId = null;
    
    const initMainGlobe = () => {
        if (globeInitialized || !mainGlobeContainer) return;
        globeInitialized = true;
        
        // Get container dimensions for responsive sizing
        const containerRect = mainGlobeContainer.getBoundingClientRect();
        const size = Math.min(containerRect.width, containerRect.height) * 0.9;
        
        // Scene setup - transparent background
        globeScene = new THREE.Scene();
        
        globeCamera = new THREE.PerspectiveCamera(45, 1, 1, 1000);
        globeCamera.position.z = 12;
        
        globeRenderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
        globeRenderer.setClearColor(0x000000, 0);
        globeRenderer.setSize(size, size);
        globeRenderer.setPixelRatio(window.devicePixelRatio);
        mainGlobeContainer.appendChild(globeRenderer.domElement);
        
        // Texture generation helpers
        const getX = (lon) => (lon + 180) * (4096 / 360);
        const getY = (lat) => ((-lat) + 90) * (2048 / 180);
        
        const drawContinentsPath = (ctx) => {
            ctx.beginPath();
            const drawPoly = (coords) => {
                ctx.moveTo(getX(coords[0][0]), getY(coords[0][1]));
                for (let i = 1; i < coords.length; i++) {
                    ctx.lineTo(getX(coords[i][0]), getY(coords[i][1]));
                }
            };
            drawPoly([[-77, 8], [-75, 11], [-60, 10], [-50, 5], [-35, -5], [-35, -10], [-39, -20], [-40, -30], [-55, -55], [-70, -55], [-75, -50], [-73, -40], [-71, -30], [-75, -20], [-81, -5], [-77, 8]]);
            drawPoly([[-165, 65], [-120, 70], [-90, 75], [-70, 70], [-60, 60], [-55, 52], [-75, 35], [-80, 25], [-82, 9], [-95, 18], [-105, 20], [-125, 35], [-125, 45], [-130, 50], [-165, 65]]);
            drawPoly([[-50, 60], [-40, 65], [-30, 80], [-60, 80], [-50, 60]]);
            drawPoly([[-15, 35], [10, 37], [30, 31], [40, 15], [51, 11], [45, -10], [40, -15], [35, -30], [20, -35], [10, -5], [5, 5], [-10, 5], [-17, 15], [-15, 35]]);
            drawPoly([[43, -25], [50, -15], [49, -12], [44, -22]]);
            drawPoly([[-10, 36], [-9, 43], [0, 50], [10, 55], [25, 70], [40, 65], [35, 45], [25, 35], [15, 40], [10, 45], [5, 42], [-10, 36]]);
            drawPoly([[-5, 50], [2, 51], [0, 58], [-6, 56]]);
            drawPoly([[40, 65], [60, 75], [100, 75], [170, 70], [140, 50], [130, 40], [120, 30], [120, 20], [110, 10], [100, 15], [90, 22], [80, 5], [70, 10], [60, 25], [50, 30], [40, 45], [40, 65]]);
            drawPoly([[130, 32], [138, 36], [142, 40], [140, 45], [135, 35]]);
            drawPoly([[100, 0], [110, -5], [140, -5], [150, -10], [130, 0]]);
            drawPoly([[113, -25], [130, -12], [145, -10], [153, -25], [150, -38], [135, -35], [115, -35], [113, -25]]);
            drawPoly([[166, -45], [174, -35], [178, -38], [168, -47]]);
            ctx.closePath();
        };
        
        // Color texture
        const createColorTexture = () => {
            const canvas = document.createElement('canvas');
            canvas.width = 4096; canvas.height = 2048;
            const ctx = canvas.getContext('2d');
            ctx.fillStyle = '#ffffff';
            ctx.fillRect(0, 0, 4096, 2048);
            ctx.shadowColor = 'rgba(0, 0, 0, 0.4)';
            ctx.shadowBlur = 30;
            ctx.fillStyle = '#dcdcdc';
            ctx.strokeStyle = '#555555';
            ctx.lineWidth = 4;
            ctx.lineJoin = 'round';
            drawContinentsPath(ctx);
            ctx.fill();
            ctx.stroke();
            ctx.globalCompositeOperation = 'source-atop';
            for (let i = 0; i < 2000; i++) {
                const x = Math.random() * 4096;
                const y = Math.random() * 2048;
                const r = 5 + Math.random() * 20;
                ctx.fillStyle = 'rgba(200, 200, 200, 0.1)';
                ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI*2); ctx.fill();
            }
            ctx.shadowColor = 'transparent';
            ctx.strokeStyle = '#cccccc';
            ctx.lineWidth = 1;
            ctx.beginPath();
            for(let x = 0; x < 4096; x += 60) { ctx.moveTo(x, 0); ctx.lineTo(x, 2048); }
            for(let y = 0; y < 2048; y += 60) { ctx.moveTo(0, y); ctx.lineTo(4096, y); }
            ctx.stroke();
            return new THREE.CanvasTexture(canvas);
        };
        
        // Height texture
        const createHeightTexture = () => {
            const canvas = document.createElement('canvas');
            canvas.width = 4096; canvas.height = 2048;
            const ctx = canvas.getContext('2d');
            ctx.fillStyle = '#000000';
            ctx.fillRect(0, 0, 4096, 2048);
            ctx.save();
            drawContinentsPath(ctx);
            ctx.clip();
            ctx.fillStyle = '#808080';
            ctx.fillRect(0, 0, 4096, 2048);
            for (let i = 0; i < 10000; i++) {
                const x = Math.random() * 4096;
                const y = Math.random() * 2048;
                const radius = 5 + Math.random() * 30;
                const shade = Math.floor(100 + Math.random() * 155);
                const grad = ctx.createRadialGradient(x, y, 0, x, y, radius);
                grad.addColorStop(0, `rgba(${shade}, ${shade}, ${shade}, 0.5)`);
                grad.addColorStop(1, `rgba(${shade}, ${shade}, ${shade}, 0)`);
                ctx.fillStyle = grad;
                ctx.beginPath();
                ctx.arc(x, y, radius, 0, Math.PI*2);
                ctx.fill();
            }
            ctx.strokeStyle = '#e0e0e0';
            ctx.lineWidth = 2;
            drawContinentsPath(ctx);
            ctx.stroke();
            ctx.restore();
            return new THREE.CanvasTexture(canvas);
        };
        
        // Earth
        const earthGeo = new THREE.SphereGeometry(4, 128, 128);
        const earthMat = new THREE.MeshPhongMaterial({
            map: createColorTexture(),
            displacementMap: createHeightTexture(),
            displacementScale: 0.5,
            displacementBias: 0,
            color: 0xffffff,
            specular: 0x333333,
            shininess: 8
        });
        globeEarth = new THREE.Mesh(earthGeo, earthMat);
        globeScene.add(globeEarth);
        
        // Atmosphere
        const atmGeo = new THREE.SphereGeometry(4.2, 64, 64);
        const atmMat = new THREE.MeshBasicMaterial({
            color: 0x888888,
            transparent: true,
            opacity: 0.05,
            side: THREE.BackSide
        });
        const atmosphere = new THREE.Mesh(atmGeo, atmMat);
        globeScene.add(atmosphere);
        
        // Network
        const particlesCount = 100;
        const connectionDistance = 2.5;
        const sphereRadius = 4.4;
        
        globeNetworkGroup = new THREE.Group();
        globeScene.add(globeNetworkGroup);
        
        const packetColors = [0x222222, 0x333333, 0x111111];
        const particleGeo = new THREE.SphereGeometry(0.04, 8, 8);
        globeParticles = [];
        
        for (let i = 0; i < particlesCount; i++) {
            const phi = Math.acos(-1 + (2 * i) / particlesCount);
            const theta = Math.sqrt(particlesCount * Math.PI) * phi;
            const greyVal = 0.5 + Math.random() * 0.3;
            const mat = new THREE.MeshBasicMaterial({ color: new THREE.Color(greyVal, greyVal, greyVal) });
            const mesh = new THREE.Mesh(particleGeo, mat);
            mesh.position.setFromSphericalCoords(sphereRadius, phi, theta);
            mesh.position.x += (Math.random() - 0.5) * 0.2;
            mesh.position.y += (Math.random() - 0.5) * 0.2;
            mesh.position.z += (Math.random() - 0.5) * 0.2;
            mesh.userData = {
                velocity: new THREE.Vector3((Math.random() - 0.5) * 0.005, (Math.random() - 0.5) * 0.005, (Math.random() - 0.5) * 0.005),
                packetColor: packetColors[Math.floor(Math.random() * packetColors.length)]
            };
            globeNetworkGroup.add(mesh);
            globeParticles.push(mesh);
        }
        
        const lineMaterial = new THREE.LineBasicMaterial({ color: 0x999999, transparent: true, opacity: 0.2 });
        globeLineMesh = new THREE.LineSegments(new THREE.BufferGeometry(), lineMaterial);
        globeNetworkGroup.add(globeLineMesh);
        
        // Packets
        const packetGeo = new THREE.BufferGeometry();
        const packetMat = new THREE.PointsMaterial({
            size: 0.16,
            vertexColors: true,
            transparent: true,
            opacity: 0.9,
            map: (() => {
                const canvas = document.createElement('canvas');
                canvas.width = 32; canvas.height = 32;
                const ctx = canvas.getContext('2d');
                ctx.beginPath();
                ctx.arc(16, 16, 14, 0, Math.PI * 2);
                ctx.fillStyle = 'white';
                ctx.fill();
                return new THREE.CanvasTexture(canvas);
            })()
        });
        const packetSystem = new THREE.Points(packetGeo, packetMat);
        globeNetworkGroup.add(packetSystem);
        globeActivePackets = [];
        
        // Lighting
        const ambientLight = new THREE.AmbientLight(0xffffff, 0.7);
        globeScene.add(ambientLight);
        const dirLight = new THREE.DirectionalLight(0xffffff, 0.8);
        dirLight.position.set(20, 10, 20);
        globeScene.add(dirLight);
        const rimLight = new THREE.DirectionalLight(0xeeeeee, 0.3);
        rimLight.position.set(-10, 10, -20);
        globeScene.add(rimLight);
        
        // Animation loop
        const animateGlobe = () => {
            globeAnimationId = requestAnimationFrame(animateGlobe);
            
            globeEarth.rotation.y += 0.003;
            globeNetworkGroup.rotation.y += 0.0032;
            
            const linePositions = [];
            const connections = [];
            
            globeParticles.forEach((p) => {
                p.position.add(p.userData.velocity);
                p.position.normalize().multiplyScalar(sphereRadius);
            });
            
            for (let i = 0; i < globeParticles.length; i++) {
                for (let j = i + 1; j < globeParticles.length; j++) {
                    const dist = globeParticles[i].position.distanceTo(globeParticles[j].position);
                    if (dist < connectionDistance) {
                        linePositions.push(
                            globeParticles[i].position.x, globeParticles[i].position.y, globeParticles[i].position.z,
                            globeParticles[j].position.x, globeParticles[j].position.y, globeParticles[j].position.z
                        );
                        connections.push({ start: globeParticles[i].position, end: globeParticles[j].position, color: globeParticles[i].userData.packetColor });
                    }
                }
            }
            
            globeLineMesh.geometry.dispose();
            const lineGeo = new THREE.BufferGeometry();
            lineGeo.setAttribute('position', new THREE.Float32BufferAttribute(linePositions, 3));
            globeLineMesh.geometry = lineGeo;
            
            for (let k = 0; k < 5; k++) {
                if (Math.random() > 0.5 && connections.length > 0) {
                    const route = connections[Math.floor(Math.random() * connections.length)];
                    globeActivePackets.push({ start: route.start, end: route.end, progress: 0, speed: 0.01 + Math.random() * 0.02, color: new THREE.Color(route.color) });
                }
            }
            
            const packetPositions = [];
            const packetColorsArr = [];
            
            for (let i = globeActivePackets.length - 1; i >= 0; i--) {
                const pkt = globeActivePackets[i];
                pkt.progress += pkt.speed;
                if (pkt.progress >= 1) { globeActivePackets.splice(i, 1); continue; }
                const x = THREE.MathUtils.lerp(pkt.start.x, pkt.end.x, pkt.progress);
                const y = THREE.MathUtils.lerp(pkt.start.y, pkt.end.y, pkt.progress);
                const z = THREE.MathUtils.lerp(pkt.start.z, pkt.end.z, pkt.progress);
                packetPositions.push(x, y, z);
                packetColorsArr.push(pkt.color.r, pkt.color.g, pkt.color.b);
            }
            
            packetGeo.setAttribute('position', new THREE.Float32BufferAttribute(packetPositions, 3));
            packetGeo.setAttribute('color', new THREE.Float32BufferAttribute(packetColorsArr, 3));
            
            globeRenderer.render(globeScene, globeCamera);
        };
        
        animateGlobe();
        
        // Resize handler for responsive globe
        const handleGlobeResize = () => {
            if (!globeRenderer || !globeCamera || !mainGlobeContainer) return;
            
            const containerRect = mainGlobeContainer.getBoundingClientRect();
            const newSize = Math.min(containerRect.width, containerRect.height) * 0.9;
            
            globeRenderer.setSize(newSize, newSize);
            globeCamera.updateProjectionMatrix();
        };
        
        window.addEventListener('resize', handleGlobeResize);
    };
    
    // Web search animation - show globe, slide entire container down
    window.webSearchStart = () => {
        if (!mainGlobeContainer || !imageStreamContainer) return;
        
        initMainGlobe();
        mainGlobeContainer.classList.add('visible');
        imageStreamContainer.classList.add('web-active');
        
        // Trigger resize check after visibility transition
        setTimeout(() => {
            if (globeRenderer && globeCamera && mainGlobeContainer) {
                const containerRect = mainGlobeContainer.getBoundingClientRect();
                const newSize = Math.min(containerRect.width, containerRect.height) * 0.9;
                globeRenderer.setSize(newSize, newSize);
                globeCamera.updateProjectionMatrix();
            }
        }, 100);
    };
    
    // End web search animation - fade globe, slide container back up
    window.webSearchEnd = () => {
        if (!mainGlobeContainer || !imageStreamContainer) return;
        
        mainGlobeContainer.classList.remove('visible');
        imageStreamContainer.classList.remove('web-active');
    };

    // ============================================
    // SHELL TERMINAL ANIMATION
    // ============================================
    
    const shellTerminalContainer = document.getElementById('shellTerminalContainer');
    const shellCmdText = document.getElementById('shellCmdText');
    const shellStreamLine = document.getElementById('shellStreamLine');
    const shellStreamText = document.getElementById('shellStreamText');
    const shellStatusLine = document.getElementById('shellStatusLine');
    const shellStatusTag = document.getElementById('shellStatusTag');
    const shellStatusText = document.getElementById('shellStatusText');
    const shellTermTitle = document.getElementById('shellTermTitle');
    const shellCursor = document.getElementById('shellCursor');
    const shellProgress = document.getElementById('shellProgress');
    
    let shellStreamTimeout = null;
    let shellTextInterval = null;
    let shellResultInterval = null;

    const streamTextInto = (element, text, scrollContainer, onDone) => {
        element.textContent = '';
        let idx = 0;
        const step = Math.max(1, Math.floor(text.length / 60));
        const id = setInterval(() => {
            idx += step;
            if (idx >= text.length) {
                idx = text.length;
                clearInterval(id);
                if (onDone) onDone();
            }
            element.textContent = text.substring(0, idx);
            if (scrollContainer) scrollContainer.scrollTop = scrollContainer.scrollHeight;
        }, 25);
        return id;
    };

    const resetShellTerminal = () => {
        // Reset all lines to hidden
        if (shellStreamLine) { shellStreamLine.classList.remove('visible'); }
        if (shellStatusLine) { shellStatusLine.classList.remove('visible'); }
        
        // Reset content
        if (shellTermTitle) shellTermTitle.textContent = 'Shell';
        if (shellCmdText) shellCmdText.textContent = 'autouse.';
        if (shellStreamText) shellStreamText.textContent = '';
        if (shellStatusText) shellStatusText.textContent = 'running';
        
        // Reset tag to running state
        if (shellStatusTag) {
            shellStatusTag.className = 'tag run';
            shellStatusTag.textContent = '●';
        }
        
        // Show cursor and progress
        if (shellCursor) shellCursor.style.display = '';
        if (shellProgress) shellProgress.style.display = '';
        
        // Clear any pending stream timeout / intervals
        if (shellStreamTimeout) {
            clearTimeout(shellStreamTimeout);
            shellStreamTimeout = null;
        }
        if (shellTextInterval) {
            clearInterval(shellTextInterval);
            shellTextInterval = null;
        }
        if (shellResultInterval) {
            clearInterval(shellResultInterval);
            shellResultInterval = null;
        }
    };
    
    // Shell start: terminal card appears, screenshot slides down
    window.shellStart = (command, label) => {
        if (!shellTerminalContainer || !imageStreamContainer) return;

        resetShellTerminal();

        // Set the terminal title (Shell or AppleScript)
        if (shellTermTitle) shellTermTitle.textContent = label || 'Shell';

        // Set the command text
        if (shellCmdText) shellCmdText.textContent = 'autouse.';
        
        // Show container + push screenshot down
        shellTerminalContainer.classList.add('visible');
        imageStreamContainer.classList.add('shell-active');
        
        // Animate stream line after short delay — stream text progressively
        setTimeout(() => {
            if (shellStreamLine) {
                shellStreamLine.classList.add('visible');
                shellTextInterval = streamTextInto(
                    shellStreamText,
                    command || 'executing...',
                    shellStreamLine
                );
            }
        }, 300);

        // Show running status after short delay
        setTimeout(() => {
            if (shellStatusLine) shellStatusLine.classList.add('visible');
        }, 600);
    };
    
    // Shell result: show success or failure
    window.shellResult = (status, output) => {
        if (!shellTerminalContainer) return;
        
        // Hide cursor and progress bar
        if (shellCursor) shellCursor.style.display = 'none';
        if (shellProgress) shellProgress.style.display = 'none';
        
        // Truncate output for display (keep it short)
        const displayOutput = output ? (output.length > 80 ? output.substring(0, 80) + '...' : output) : '';
        
        if (status === 'success') {
            if (shellStatusTag) {
                shellStatusTag.className = 'tag ok';
                shellStatusTag.textContent = '✓';
            }
            if (shellStatusText) {
                shellResultInterval = streamTextInto(
                    shellStatusText,
                    displayOutput || 'completed',
                    shellStatusLine
                );
            }
        } else {
            if (shellStatusTag) {
                shellStatusTag.className = 'tag fail';
                shellStatusTag.textContent = '✗';
            }
            if (shellStatusText) {
                shellStatusText.style.color = 'rgba(70, 70, 70, 0.95)';
                shellResultInterval = streamTextInto(
                    shellStatusText,
                    displayOutput || 'failed',
                    shellStatusLine
                );
            }
        }
    };
    
    // Shell end: terminal card fades out, screenshot slides back up
    window.shellEnd = () => {
        if (!shellTerminalContainer || !imageStreamContainer) return;

        shellTerminalContainer.classList.remove('visible');
        imageStreamContainer.classList.remove('shell-active');

        // Reset color after fade out completes
        setTimeout(() => {
            if (shellStatusText) shellStatusText.style.color = '';
            resetShellTerminal();
        }, 700);
    };

    // =====================================================================
    // CLI streaming UI — pills for parallel CLI subprocesses during cli_await.
    // Emitted by app.py:send_cli_event_to_frontend (macOS only for now).
    // =====================================================================

    // ---------- Particle engine (loader / globe / tick) ----------
    // Adapted from all_cli_animation.html. 800 particles morph between three
    // shapes via a 1.5s pinch+swirl ease. State-driven (not on a timeline)
    // so pill events (web start, web end, complete) trigger transitions.
    const PARTICLE_COLOR         = '#9ca3af';
    const P_OUTER_SPOKES         = 12;
    const P_INNER_SPOKES         = 8;
    const P_PER_SPOKE            = 40;
    const P_TOTAL                = (P_OUTER_SPOKES + P_INNER_SPOKES) * P_PER_SPOKE;
    const P_GLOBE_R              = 36;
    const P_TICK_R               = 36;
    const P_TRANSITION_MS        = 1500;
    const P_CANVAS_CSS           = 20;
    const P_LOCAL_SCALE          = (P_CANVAS_CSS / 2) / 42;

    function _easeInOutCubic(x) {
        return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
    }
    function _distToSegment(p, v, w) {
        const l2 = (w.x - v.x) * (w.x - v.x) + (w.y - v.y) * (w.y - v.y);
        if (l2 === 0) return Math.hypot(p.x - v.x, p.y - v.y);
        let t = ((p.x - v.x) * (w.x - v.x) + (p.y - v.y) * (w.y - v.y)) / l2;
        t = Math.max(0, Math.min(1, t));
        return Math.hypot(p.x - (v.x + t * (w.x - v.x)), p.y - (v.y + t * (w.y - v.y)));
    }
    function _generateTickData(targetCount) {
        let bestData = [];
        let minDiff = Infinity;
        const p1 = { x: -14, y: 2 }, p2 = { x: -4, y: 12 }, p3 = { x: 16, y: -8 };
        const CUTOUT_THICKNESS = 6.5;
        for (let density = 0.8; density < 3.0; density += 0.01) {
            const temp = [];
            const rings = Math.floor(P_TICK_R * density);
            for (let i = 0; i <= rings; i++) {
                const r = (i / rings) * P_TICK_R;
                const pts = i === 0 ? 1 : Math.floor(2 * Math.PI * r * density);
                for (let j = 0; j < pts; j++) {
                    const theta = (j / pts) * Math.PI * 2;
                    const px = r * Math.cos(theta);
                    const py = r * Math.sin(theta);
                    const d1 = _distToSegment({ x: px, y: py }, p1, p2);
                    const d2 = _distToSegment({ x: px, y: py }, p2, p3);
                    if (d1 > CUTOUT_THICKNESS && d2 > CUTOUT_THICKNESS) {
                        temp.push({ x: px, y: py });
                    }
                }
            }
            if (Math.abs(temp.length - targetCount) < minDiff) {
                minDiff = Math.abs(temp.length - targetCount);
                bestData = temp;
                if (minDiff === 0) break;
            }
        }
        while (bestData.length > targetCount) bestData.splice(Math.floor(Math.random() * bestData.length), 1);
        while (bestData.length < targetCount) bestData.push({ x: bestData[0].x, y: bestData[0].y });
        return bestData;
    }
    let _cachedTickData = null;
    function _getTickDataCached() {
        if (!_cachedTickData) _cachedTickData = _generateTickData(P_TOTAL);
        return _cachedTickData;
    }
    function _initParticleSet() {
        const loaderData = [];
        const globeData = [];
        for (let i = 0; i < P_OUTER_SPOKES; i++) {
            const angle = (i / P_OUTER_SPOKES) * Math.PI * 2;
            for (let j = 0; j < P_PER_SPOKE; j++) {
                const t = j / (P_PER_SPOKE - 1);
                loaderData.push({ type: 'outer', angle, r: 32 + t * 10, pRadius: 2.5 });
            }
        }
        for (let i = 0; i < P_INNER_SPOKES; i++) {
            const angle = (i / P_INNER_SPOKES) * Math.PI * 2;
            for (let j = 0; j < P_PER_SPOKE; j++) {
                const t = j / (P_PER_SPOKE - 1);
                loaderData.push({ type: 'inner', angle, r: 16 + t * 6, pRadius: 1.8 });
            }
        }
        for (let i = 0; i < 12; i++) {
            const theta = (i / 12) * Math.PI * 2;
            for (let j = 0; j < 40; j++) {
                const phi = (j / 39) * Math.PI;
                globeData.push({ theta, phi });
            }
        }
        for (let i = 0; i < 8; i++) {
            const phi = ((i + 1) / 9) * Math.PI;
            for (let j = 0; j < 40; j++) {
                const theta = (j / 40) * Math.PI * 2;
                globeData.push({ theta, phi });
            }
        }
        const tickData = _getTickDataCached().slice();
        // Per-engine destination shuffle so swarm scatters differently each spawn.
        for (let i = globeData.length - 1; i > 0; i--) {
            const j = Math.floor(Math.random() * (i + 1));
            [globeData[i], globeData[j]] = [globeData[j], globeData[i]];
            const k = Math.floor(Math.random() * (i + 1));
            [tickData[i], tickData[k]] = [tickData[k], tickData[i]];
        }
        const out = new Array(P_TOTAL);
        for (let i = 0; i < P_TOTAL; i++) {
            out[i] = { l: loaderData[i], g: globeData[i], t: tickData[i] };
        }
        return out;
    }
    function _getShapePos(shape, p, time) {
        if (shape === 'l') {
            const outerA = time * 0.0015;
            const innerA = -time * 0.0025;
            const a = p.l.angle + (p.l.type === 'outer' ? outerA : innerA);
            return { x: Math.cos(a) * p.l.r, y: Math.sin(a) * p.l.r, z: 0, pRadius: p.l.pRadius };
        }
        if (shape === 'g') {
            const spin = time * 0.001;
            const theta = p.g.theta + spin;
            return {
                x: Math.sin(p.g.phi) * Math.cos(theta) * P_GLOBE_R,
                y: Math.cos(p.g.phi) * P_GLOBE_R,
                z: Math.sin(p.g.phi) * Math.sin(theta) * P_GLOBE_R,
                pRadius: 1.2,
            };
        }
        return { x: p.t.x, y: p.t.y, z: 0, pRadius: 2.4 };
    }

    // Single shared rAF — every active engine renders in lockstep.
    const _engineManager = { engines: new Set(), rafId: null };
    function _engineFrame(time) {
        _engineManager.rafId = null;
        for (const eng of _engineManager.engines) {
            try { eng.render(time); } catch (e) { console.warn('[particle] render', e); }
        }
        if (_engineManager.engines.size > 0) {
            _engineManager.rafId = requestAnimationFrame(_engineFrame);
        }
    }
    function _registerEngine(eng) {
        _engineManager.engines.add(eng);
        if (!_engineManager.rafId) {
            _engineManager.rafId = requestAnimationFrame(_engineFrame);
        }
    }
    function _unregisterEngine(eng) {
        _engineManager.engines.delete(eng);
    }

    function createParticleEngine(canvas) {
        if (!canvas) return null;
        const ctx = canvas.getContext('2d');
        const dpr = window.devicePixelRatio || 1;
        canvas.width = P_CANVAS_CSS * dpr;
        canvas.height = P_CANVAS_CSS * dpr;
        canvas.style.width = P_CANVAS_CSS + 'px';
        canvas.style.height = P_CANVAS_CSS + 'px';
        ctx.scale(dpr, dpr);

        const cx = P_CANVAS_CSS / 2;
        const cy = P_CANVAS_CSS / 2;
        const particles = _initParticleSet();

        let originShape = 'l';
        let currentShape = 'l';
        let targetShape = 'l';
        let transitionStart = 0;
        let isTransitioning = false;
        let isStatic = false;        // true once tick has fully settled
        let destroyed = false;

        const engine = {
            canvas,
            get shape() { return currentShape; },
            setShape(name) {
                if (destroyed) return;
                const code = name === 'globe' ? 'g' : name === 'tick' ? 't' : 'l';
                if (code === targetShape && !isTransitioning) return;
                originShape = currentShape;
                targetShape = code;
                isTransitioning = true;
                transitionStart = performance.now();
                isStatic = false;
                _registerEngine(engine);
            },
            render(time) {
                if (destroyed || isStatic) return;
                let ePhase = 0;
                if (isTransitioning) {
                    const elapsed = time - transitionStart;
                    if (elapsed >= P_TRANSITION_MS) {
                        currentShape = targetShape;
                        isTransitioning = false;
                        ePhase = 0;
                    } else {
                        ePhase = _easeInOutCubic(elapsed / P_TRANSITION_MS);
                    }
                }
                const shape1 = isTransitioning ? originShape : currentShape;
                const shape2 = isTransitioning ? targetShape : currentShape;
                const pinchFactor = 1.0 - Math.sin(ePhase * Math.PI) * 0.9;
                const swirlFactor = Math.sin(ePhase * Math.PI) * Math.PI * 1.5;

                let vOpacity = 0.0;
                let pTargetAlpha = 1.0;
                if (shape1 === 't' && shape2 === 't') {
                    vOpacity = 1.0; pTargetAlpha = 0.0;
                } else if (shape2 === 't') {
                    vOpacity = Math.pow(ePhase, 4);
                    pTargetAlpha = 1.0 - Math.pow(ePhase, 4);
                } else if (shape1 === 't') {
                    vOpacity = Math.pow(1 - ePhase, 4);
                    pTargetAlpha = 1.0 - Math.pow(1 - ePhase, 4);
                }

                ctx.clearRect(0, 0, P_CANVAS_CSS, P_CANVAS_CSS);
                ctx.fillStyle = PARTICLE_COLOR;
                const perspective = 300;

                for (let i = 0; i < particles.length; i++) {
                    const p = particles[i];
                    const pos1 = _getShapePos(shape1, p, time);
                    const pos2 = _getShapePos(shape2, p, time);
                    let mX = (pos1.x + (pos2.x - pos1.x) * ePhase) * pinchFactor;
                    let mY = (pos1.y + (pos2.y - pos1.y) * ePhase) * pinchFactor;
                    let mZ = (pos1.z + (pos2.z - pos1.z) * ePhase) * pinchFactor;
                    const sN = Math.sin(swirlFactor);
                    const cN = Math.cos(swirlFactor);
                    const rx = mX * cN - mY * sN;
                    const ry = mX * sN + mY * cN;
                    mX = rx; mY = ry;
                    const projScale = perspective / (perspective + mZ);
                    const pX = cx + mX * P_LOCAL_SCALE * projScale;
                    const pY = cy + mY * P_LOCAL_SCALE * projScale;
                    let opacity = 1.0;
                    const is3DMix = (shape1 === 'g' ? 1 - ePhase : 0) + (shape2 === 'g' ? ePhase : 0);
                    if (is3DMix > 0) {
                        const depthOpacity = 0.3 + 0.7 * (1 - (mZ + P_GLOBE_R) / (2 * P_GLOBE_R));
                        opacity = 1.0 - is3DMix * (1.0 - depthOpacity);
                    }
                    const finalOpacity = opacity * pTargetAlpha;
                    if (finalOpacity > 0.01) {
                        ctx.globalAlpha = Math.max(0.01, finalOpacity);
                        const pR = pos1.pRadius + (pos2.pRadius - pos1.pRadius) * ePhase;
                        const size = pR * P_LOCAL_SCALE * projScale;
                        ctx.beginPath();
                        ctx.arc(pX, pY, Math.max(0.4, size), 0, Math.PI * 2);
                        ctx.fill();
                    }
                }

                if (vOpacity > 0.01) {
                    ctx.save();
                    ctx.translate(cx, cy);
                    ctx.scale(pinchFactor * P_LOCAL_SCALE, pinchFactor * P_LOCAL_SCALE);
                    ctx.rotate(swirlFactor);
                    ctx.globalAlpha = vOpacity;
                    ctx.fillStyle = PARTICLE_COLOR;
                    ctx.beginPath();
                    ctx.arc(0, 0, P_TICK_R, 0, Math.PI * 2);
                    ctx.fill();
                    ctx.globalCompositeOperation = 'destination-out';
                    ctx.lineWidth = 13;
                    ctx.lineCap = 'round';
                    ctx.lineJoin = 'round';
                    ctx.beginPath();
                    ctx.moveTo(-14, 2);
                    ctx.lineTo(-4, 12);
                    ctx.lineTo(16, -8);
                    ctx.stroke();
                    ctx.restore();
                }
                ctx.globalAlpha = 1.0;

                // Tick steady-state: final frame is drawn — stop animating. The
                // canvas keeps the last buffer, so the solid tick stays visible.
                if (!isTransitioning && currentShape === 't') {
                    isStatic = true;
                    _unregisterEngine(engine);
                }
            },
            destroy() {
                destroyed = true;
                isStatic = true;
                _unregisterEngine(engine);
            },
        };
        _registerEngine(engine);
        return engine;
    }

    // Pill ↔ engine attachment so we can find an engine by pill or by taskId.
    const _pillEngines = new WeakMap();  // pill element -> engine
    function _attachEngine(pill) {
        if (!pill || _pillEngines.has(pill)) return null;
        const canvas = pill.querySelector('.cli-pill-canvas');
        if (!canvas) return null;
        const eng = createParticleEngine(canvas);
        if (eng) _pillEngines.set(pill, eng);
        return eng;
    }
    function _detachEngine(pill) {
        if (!pill) return;
        const eng = _pillEngines.get(pill);
        if (eng) {
            eng.destroy();
            _pillEngines.delete(pill);
        }
    }
    function _engineForPill(pill) {
        return pill ? _pillEngines.get(pill) : null;
    }

    const cliStreamList = document.getElementById('cliStreamList');
    const cliPillTemplate = document.getElementById('cliPillTemplate');

    function findCliPill(taskId) {
        if (!cliStreamList) return null;
        return cliStreamList.querySelector(
            `.cli-pill[data-task-id="${CSS.escape(String(taskId))}"]`
        );
    }

    window.cliTaskStart = (taskId, description) => {
        console.log('[cli] task_start', taskId, description);
        if (!cliStreamList || !cliPillTemplate) {
            console.warn('[cli] missing cliStreamList or cliPillTemplate');
            return;
        }
        if (findCliPill(taskId)) return;  // dedupe if event arrives twice
        const pill = cliPillTemplate.content.firstElementChild.cloneNode(true);
        pill.dataset.taskId = String(taskId);
        const cmdEl = pill.querySelector('.cli-pill-cmd');
        if (cmdEl) cmdEl.textContent = description || '';
        cliStreamList.appendChild(pill);
        _attachEngine(pill);
        // A new running CLI pill means "all siblings complete" is no longer
        // true — cancel any in-flight tick-fade timer. It'll re-arm when this
        // new pill eventually completes.
        if (_tickFadeTimer) { clearTimeout(_tickFadeTimer); _tickFadeTimer = null; }
    };

    // Per-word fade-in stagger. Higher = calmer reading pace.
    const CLI_WORD_STAGGER_MS  = 45;
    // Hold a finished page (full pill width filled) before clearing for the next page.
    const CLI_PAGE_HOLD_MS     = 550;
    // Hold between distinct lines (after the final page of a line completes).
    const CLI_LINE_HOLD_MS     = 260;

    // Per-pill line queue + runner. Incoming task_line events get queued and
    // played back one at a time so the user always sees each line stream
    // smoothly, even when the agent dumps 10 lines of raw response in one
    // millisecond. We're explicitly OK with the UI lagging behind real time —
    // smoothness matters more than catching up.
    //
    // Each line is "paginated": words stream left-to-right; when the next
    // word would overflow the pill width, the current page holds, the
    // output clears, and that word starts the next page from the left.
    const _cliPillRunners = new WeakMap();

    function _getRunner(pill) {
        let runner = _cliPillRunners.get(pill);
        if (!runner) {
            runner = { queue: [], running: false };
            _cliPillRunners.set(pill, runner);
        }
        return runner;
    }

    function _pumpCliRunner(pill, runner) {
        if (runner.running) return;
        if (runner.queue.length === 0) return;
        runner.running = true;
        const { text, stream } = runner.queue.shift();

        const out = pill.querySelector('.cli-output');
        if (!out) {
            runner.running = false;
            _pumpCliRunner(pill, runner);
            return;
        }

        const words = String(text).split(/\s+/).filter(w => w.length > 0);
        const lineClass = stream === 'err' ? 'cli-line cli-line-err' : 'cli-line cli-line-out';

        if (words.length === 0) {
            runner.running = false;
            _pumpCliRunner(pill, runner);
            return;
        }

        let pageDiv = null;
        const startNewPage = () => {
            pageDiv = document.createElement('div');
            pageDiv.className = lineClass;
            out.replaceChildren(pageDiv);
        };
        startNewPage();

        let i = 0;
        const tick = () => {
            if (i >= words.length) {
                // Final page rendered — hold, then drop the run flag so the
                // next queued line gets pulled.
                setTimeout(() => {
                    runner.running = false;
                    _pumpCliRunner(pill, runner);
                }, CLI_LINE_HOLD_MS);
                return;
            }

            const isFirstOnPage = pageDiv.childElementCount === 0;
            const span = document.createElement('span');
            span.className = 'cli-word';
            span.textContent = (isFirstOnPage ? '' : ' ') + words[i];
            pageDiv.appendChild(span);

            // Did this word push past the pill's right edge? Measure on the
            // page div itself — `.cli-line` has overflow:hidden so the
            // overflow doesn't propagate up to `.cli-output`. If the word
            // doesn't fit (and it isn't the only word on this page), retract
            // it, hold the current page, then start fresh with this word at
            // the left edge of a new page.
            const overflowed = pageDiv.scrollWidth > pageDiv.clientWidth + 1;
            if (overflowed && !isFirstOnPage) {
                pageDiv.removeChild(span);
                setTimeout(() => {
                    startNewPage();
                    tick();  // retry placing this word as the start of the new page
                }, CLI_PAGE_HOLD_MS);
                return;
            }

            // Word fits (or it's a lone oversized word we accept as-is).
            i++;
            setTimeout(tick, CLI_WORD_STAGGER_MS);
        };

        tick();
    }

    window.cliTaskLine = (taskId, line, stream) => {
        console.log('[cli] task_line', taskId, stream, line);
        const pill = findCliPill(taskId);
        if (!pill) {
            console.warn('[cli] no pill found for', taskId);
            return;
        }
        const text = line == null ? '' : String(line);
        if (text.trim() === '') return;  // skip blanks so the pill never flashes empty
        // Real line wins over filler. Stop the filler loop; if this pill still
        // has running minions, the next idle window will re-arm filler.
        const fs = _fillerState.get(taskId);
        if (fs) {
            _stopFiller(taskId);
            if (fs.hasMinion) _scheduleFillerStart(taskId);
        }
        const runner = _getRunner(pill);
        runner.queue.push({ text, stream });
        _pumpCliRunner(pill, runner);
    };

    window.cliTaskEnd = (taskId, status, summary) => {
        const pill = findCliPill(taskId);
        if (!pill) return;
        const finalStatus = status || 'complete';
        pill.dataset.status = finalStatus;
        pill.classList.add('complete');
        // Parent's done — stop any in-flight filler chatter (minion or web).
        _stopFiller(taskId);
        _fillerState.delete(taskId);
        _stopWebFiller(taskId);
        // Trigger the canvas tick on success; on error/stopped the canvas
        // hides via CSS and the legacy ✕ glyph paints over.
        const eng = _engineForPill(pill);
        if (eng && finalStatus === 'complete') {
            eng.setShape('tick');
            _registerPendingTickFade(pill);
        }
        if (summary) {
            // Route the summary through the same paginated queue as regular
            // lines so it streams in with the same calm pacing.
            const runner = _getRunner(pill);
            runner.queue.push({ text: summary, stream: 'summary' });
            _pumpCliRunner(pill, runner);
        }
    };

    const chatWrapper = document.getElementById('chatWrapper');
    // llmWrapper is already declared higher up (line ~23) — reuse that.

    // Whether split-layout was on the chat/llm wrappers when cli-await began,
    // so cliAwaitEnd can restore them to that state cleanly.
    let _cliPrevSplit = false;

    window.cliAwaitStart = (reason) => {
        console.log('[cli] await_start', reason);
        // Slide out the screenshot panel.
        if (imageStreamContainer) imageStreamContainer.classList.remove('agent-visible');
        // Drop split-layout so the chat box snaps back to its initial big
        // centered state (the base .chat-container-wrapper rule wins). This
        // is what the user wants: full-width chat box during cli_await.
        if (chatWrapper) {
            _cliPrevSplit = chatWrapper.classList.contains('split-layout');
            chatWrapper.classList.remove('split-layout');
            chatWrapper.classList.add('cli-mode');
        }
        if (llmWrapper) llmWrapper.classList.remove('split-layout');
        document.body.classList.add('cli-mode');  // hides LLM dropdown + settings cog
    };

    window.cliAwaitEnd = () => {
        console.log('[cli] await_end');
        if (chatWrapper) {
            chatWrapper.classList.remove('cli-mode');
            if (_cliPrevSplit) chatWrapper.classList.add('split-layout');
        }
        if (llmWrapper && _cliPrevSplit) llmWrapper.classList.add('split-layout');
        document.body.classList.remove('cli-mode');
        // Restore the screenshot panel.
        if (imageStreamContainer) imageStreamContainer.classList.add('agent-visible');
        // Clear pills after the fade-out finishes (matches the 0.4s transition).
        setTimeout(() => {
            if (!cliStreamList) return;
            // Free every engine first so the shared rAF loop drains.
            for (const pill of cliStreamList.querySelectorAll('.cli-pill')) {
                _detachEngine(pill);
            }
            _pendingTickFadeReset();
            cliStreamList.innerHTML = '';
        }, 450);
    };

    // =====================================================================
    // Minion pill choreography (narrower, darker children of CLI pills).
    // Birth: drop top-to-bottom, one at a time (~120ms apart).
    // Death: when ALL minion siblings of the same parent are complete,
    //        collapse bottom-to-top (last absorbed first), each absorb
    //        staggered ~150ms apart, fading into the parent's bottom edge.
    // =====================================================================

    const cliMinionPillTemplate = document.getElementById('cliMinionPillTemplate');

    const MINION_DROP_STAGGER_MS    = 120;
    // Wait long enough for the last-completing minion's loader→tick morph
    // (1500 ms) to fully form before the absorb cascade starts swallowing
    // pills upward. Without this you'd see the tick begin morphing in then
    // get yanked away mid-frame.
    const MINION_ABSORB_DELAY_MS    = 1700;
    const MINION_ABSORB_STAGGER_MS  = 150;

    // Per-parent drop queue so events arriving in a burst still cascade visually.
    const _minionDropQueue = new Map();  // parentTaskId -> { queue: [...], running: bool }

    // ---------- Filler phrase loop ----------
    // While a parent CLI pill has running minions but is itself silent (no new
    // lines streaming), the pill goes blank and looks frozen. Push playful
    // status phrases into the parent's runner so the user knows it's alive and
    // waiting on its minions. Stops the moment a real line comes in or the
    // minion batch finishes.
    const FILLER_PHRASES = [
        'summoned minions…',
        'digging through the codebase…',
        "don't bother me, i'm busy still",
        'reticulating splines…',
        'consulting the rubber duck…',
        'untangling spaghetti…',
        'watching minions go brrr…',
        'this is fine, everything is fine…',
        'spinning up neurons…',
        'arguing with the linter…',
        'minions are reading… patience, human',
        'pondering the orb…',
        'grepping the unknown…',
        'feeding the hamsters…',
        'still thinking, hold tight…',
        'writing tiny love letters to stdout…',
        'asking stack overflow nicely…',
        'looking for the missing semicolon…',
        'blaming the intern…',
        'performing arcane git rituals…',
        'have you tried turning it off and on…',
        'just one more refactor, i promise…',
        'regex go brrr…',
        'negotiating with the type checker…',
        "Schrödinger's bug: works on my machine…",
        'pretending to understand recursion…',
        'this codebase has feelings too…',
        'arguing with prettier…',
        'i swear i tested this earlier…',
        "checking if it's a feature, not a bug…",
        'the code works, nobody knows why…',
        'reading documentation as last resort…',
        'blaming the cache…',
        'praying to the build gods…',
        'git blame says it was past me…',
        'compiling existential dread…',
        'tabs vs spaces war ongoing…',
        'training a goldfish to write tests…',
        'minions arguing over indentation…',
        'still cheaper than a senior dev…',
        'pushing to prod on a friday…',
        'one does not simply async in python…',
        '404: motivation not found…',
        'rewriting it in rust… mentally…',
        "petting the dog, brb…",
        'yelling politely at the json…',
        "checking if it's plugged in…",
        'the cake is a bug…',
        'explaining mondays to the AI…',
        'deploying vibes…',
        'this stack trace feels personal…',
        'i was promised flying cars, got jira…',
        'writing tests… eventually…',
        'minions on coffee break…',
        "this wasn't in the spec…",
        'ctrl-z is my therapist…',
        'running from technical debt…',
        'console.log debugger gang…',
        'the docs lied to us…',
        'trying to remember what i was doing…',
        'rebooting reality…',
        "yes, that's a feature now…",
        'speedrun: any% blame git…',
        'thinking too hard, please wait…',
        'yet another deeply nested if…',
        'promise resolved with disappointment…',
        'hot reload, cold coffee…',
        'aligning ducks in rows…',
        'one liner that took two hours…',
        'naming things, the hardest problem…',
        'off-by-one somewhere, definitely…',
        'loading more excuses…',
        'the bug is in another castle…',
        'your code is fine, the universe is broken…',
        'the linter has strong opinions…',
        'minion overheard saying lgtm…',
        'convincing the tests to pass…',
        'renaming the variable to fix it…',
        'drowning in callback hell…',
        '73 unread warnings, vibes only…',
        "yes it works, no i don't know why…",
        'minions found 47 todos, ignored all…',
        'scrolling error logs like reels…',
        'two minions, one task…',
        'sacrificing a keyboard to the demo gods…',
        'undoing the undo…',
        'reading the error message, finally…',
        'minions whispering to each other…',
        'the algorithm has thoughts…',
        'trying not to break prod…',
        'minion union meeting in progress…',
        'shaking the magic 8-ball…',
        'asking the cat for code review…',
        'running tests with fingers crossed…',
        'exorcising the legacy code…',
        'i promise this is the last bug…',
        'binary search through 200 tabs…',
        'feature creep is a feature now…',
        'minions found a TODO from 2014…',
        'deprecated, but still working…',
        'putting console.logs in production…',
        'redefining what "done" means…',
    ];
    const FILLER_IDLE_MS     = 1800;  // silence before filler kicks in
    const FILLER_INTERVAL_MS = 3500;  // gap between filler phrases

    const _fillerState = new Map();  // parentTaskId -> { active, hasMinion, bag, lastIdx, idleTimer, tickTimer }

    function _ensureFiller(parentTaskId) {
        let s = _fillerState.get(parentTaskId);
        if (!s) {
            s = {
                active: false,
                hasMinion: false,
                bag: [],         // shuffle-bag: indices yet to show this cycle
                lastIdx: -1,     // last shown index (used to dedupe across reshuffles)
                idleTimer: null,
                tickTimer: null,
            };
            _fillerState.set(parentTaskId, s);
        }
        return s;
    }

    // Shuffle-bag picker: pop a random unseen phrase. When the bag empties
    // (full pool consumed), reshuffle the whole pool — so we get the entire
    // 100 covered before any repeats, then 100 again, etc. Tiny dedupe step
    // ensures we never get the same phrase back-to-back across a reshuffle.
    function _nextFillerPhrase(s) {
        if (!s.bag || s.bag.length === 0) {
            const bag = FILLER_PHRASES.map((_, i) => i);
            for (let i = bag.length - 1; i > 0; i--) {
                const j = Math.floor(Math.random() * (i + 1));
                [bag[i], bag[j]] = [bag[j], bag[i]];
            }
            // Avoid repeating the most recent phrase as the first of the new
            // cycle. If the top of the bag (next to pop) matches lastIdx,
            // swap it with the bottom.
            if (s.lastIdx >= 0 && bag.length > 1 && bag[bag.length - 1] === s.lastIdx) {
                [bag[bag.length - 1], bag[0]] = [bag[0], bag[bag.length - 1]];
            }
            s.bag = bag;
        }
        const idx = s.bag.pop();
        s.lastIdx = idx;
        return FILLER_PHRASES[idx];
    }

    function _stopFiller(parentTaskId) {
        const s = _fillerState.get(parentTaskId);
        if (!s) return;
        s.active = false;
        if (s.idleTimer) { clearTimeout(s.idleTimer); s.idleTimer = null; }
        if (s.tickTimer) { clearTimeout(s.tickTimer); s.tickTimer = null; }
    }

    function _scheduleFillerStart(parentTaskId) {
        const s = _ensureFiller(parentTaskId);
        if (!s.hasMinion) return;
        if (s.idleTimer) clearTimeout(s.idleTimer);
        s.idleTimer = setTimeout(() => {
            s.idleTimer = null;
            if (!s.hasMinion) return;
            s.active = true;
            const tickFiller = () => {
                if (!s.active) return;
                const pill = findCliPill(parentTaskId);
                if (!pill) { s.active = false; return; }
                const phrase = _nextFillerPhrase(s);
                const runner = _getRunner(pill);
                runner.queue.push({ text: phrase, stream: 'stdout' });
                _pumpCliRunner(pill, runner);
                s.tickTimer = setTimeout(tickFiller, FILLER_INTERVAL_MS);
            };
            tickFiller();
        }, FILLER_IDLE_MS);
    }

    // ---------- Web-loading filler (per-pill, looped while web tool active) ----------
    const WEB_FILLER_PHRASES = [
        'scraping the interwebs…',
        'intent searching…',
        'asking the search gods nicely…',
        'crawling the web like a polite spider…',
        'opening 1000 tabs in spirit…',
        'fetching truth from the void…',
        'interrogating wikipedia…',
        'reading 47 stack overflow answers…',
        'ranking results by vibes…',
        'cleaning the data with bare hands…',
    ];
    const WEB_FILLER_INTERVAL_MS = 3500;
    const _webFillerState = new Map();  // taskId -> { bag, lastIdx, tickTimer, active }

    function _nextWebFillerPhrase(s) {
        if (!s.bag || s.bag.length === 0) {
            const bag = WEB_FILLER_PHRASES.map((_, i) => i);
            for (let i = bag.length - 1; i > 0; i--) {
                const j = Math.floor(Math.random() * (i + 1));
                [bag[i], bag[j]] = [bag[j], bag[i]];
            }
            if (s.lastIdx >= 0 && bag.length > 1 && bag[bag.length - 1] === s.lastIdx) {
                [bag[bag.length - 1], bag[0]] = [bag[0], bag[bag.length - 1]];
            }
            s.bag = bag;
        }
        const idx = s.bag.pop();
        s.lastIdx = idx;
        return WEB_FILLER_PHRASES[idx];
    }

    function _startWebFiller(taskId) {
        if (_webFillerState.has(taskId) && _webFillerState.get(taskId).active) return;
        const s = { bag: [], lastIdx: -1, tickTimer: null, active: true };
        _webFillerState.set(taskId, s);
        const tick = () => {
            if (!s.active) return;
            const pill = findCliPill(taskId);
            if (!pill) { s.active = false; return; }
            const phrase = _nextWebFillerPhrase(s);
            const runner = _getRunner(pill);
            runner.queue.push({ text: phrase, stream: 'stdout' });
            _pumpCliRunner(pill, runner);
            s.tickTimer = setTimeout(tick, WEB_FILLER_INTERVAL_MS);
        };
        tick();
    }

    function _stopWebFiller(taskId) {
        const s = _webFillerState.get(taskId);
        if (!s) return;
        s.active = false;
        if (s.tickTimer) { clearTimeout(s.tickTimer); s.tickTimer = null; }
        _webFillerState.delete(taskId);
    }

    // ---------- Tick-fade timing (CLI parent pills only) ----------
    // Each CLI parent pill that completes successfully shows its canvas tick.
    // Tick stays visible while *any* sibling CLI pill is still running. Once
    // every CLI pill in the stream is .complete, we hold for 1s and fade
    // every pending pill's canvas together.
    const TICK_FADE_HOLD_MS = 1000;
    const _pendingTickFade = new Set();  // pill elements
    let _tickFadeTimer = null;

    function _allCliPillsComplete() {
        if (!cliStreamList) return false;
        const all = cliStreamList.querySelectorAll('.cli-pill:not(.minion)');
        if (all.length === 0) return false;
        for (const p of all) if (!p.classList.contains('complete')) return false;
        return true;
    }
    function _registerPendingTickFade(pill) {
        _pendingTickFade.add(pill);
        _maybeStartTickFadeTimer();
    }
    function _maybeStartTickFadeTimer() {
        if (_tickFadeTimer) { clearTimeout(_tickFadeTimer); _tickFadeTimer = null; }
        if (!_allCliPillsComplete()) return;
        _tickFadeTimer = setTimeout(() => {
            _tickFadeTimer = null;
            for (const pill of _pendingTickFade) {
                if (!pill.isConnected) continue;
                const canvas = pill.querySelector('.cli-pill-canvas');
                if (canvas) canvas.classList.add('canvas-faded');
                pill.classList.add('show-status-glyph');
            }
            _pendingTickFade.clear();
        }, TICK_FADE_HOLD_MS);
    }
    function _pendingTickFadeReset() {
        if (_tickFadeTimer) { clearTimeout(_tickFadeTimer); _tickFadeTimer = null; }
        _pendingTickFade.clear();
    }

    function _findMinionPill(taskId) {
        if (!cliStreamList) return null;
        return cliStreamList.querySelector(
            `.cli-pill.minion[data-task-id="${CSS.escape(String(taskId))}"]`
        );
    }

    function _findLastMinionForParent(parentTaskId) {
        if (!cliStreamList) return null;
        // Look up wrappers (which carry the layout slot in flex flow) so insertion
        // appends below the previous wrapper, not inside it.
        const all = cliStreamList.querySelectorAll(
            `.cli-minion-wrap[data-parent-task-id="${CSS.escape(String(parentTaskId))}"]`
        );
        return all.length > 0 ? all[all.length - 1] : null;
    }

    function _siblingMinions(parentTaskId) {
        if (!cliStreamList) return [];
        return Array.from(cliStreamList.querySelectorAll(
            `.cli-pill.minion[data-parent-task-id="${CSS.escape(String(parentTaskId))}"]`
        ));
    }

    function _spawnMinionPill(parentTaskId, taskId, query) {
        if (!cliStreamList || !cliMinionPillTemplate) return;
        if (_findMinionPill(taskId)) return;  // dedupe
        const parentPill = findCliPill(parentTaskId);
        if (!parentPill) {
            console.warn('[minion] no parent pill found for', parentTaskId);
            return;
        }
        const pill = cliMinionPillTemplate.content.firstElementChild.cloneNode(true);
        pill.dataset.taskId = String(taskId);
        pill.dataset.parentTaskId = String(parentTaskId);
        const cmdEl = pill.querySelector('.cli-pill-cmd');
        if (cmdEl) cmdEl.textContent = query || '';

        // Wrap in a clip container. The wrapper owns the layout slot (height
        // animates 0 → --minion-h) while the inner pill translates -100% → 0.
        // Together they produce a real geometric "slide out from behind the
        // pill above" — the wrapper's overflow:hidden clips against its top
        // edge, which sits right under the predecessor's bottom edge.
        const wrap = document.createElement('div');
        wrap.className = 'cli-minion-wrap';
        wrap.dataset.parentTaskId = String(parentTaskId);
        wrap.dataset.taskId = String(taskId);
        wrap.appendChild(pill);

        // Insert below the last existing minion wrapper of this parent (so the
        // stack grows downward in dispatch order); otherwise right after the
        // parent pill.
        const insertAfter = _findLastMinionForParent(parentTaskId) || parentPill;
        insertAfter.insertAdjacentElement('afterend', wrap);
        _attachEngine(pill);

        // Measure the inner pill's natural rendered height and lock the wrapper
        // to that exact value via --minion-h. Without this, the wrapper used a
        // hardcoded fallback that overshot the pill's actual height, leaving
        // empty space inside the wrapper that bloated the gap to the next
        // sibling. We measure on rAF so the browser has computed layout once.
        requestAnimationFrame(() => {
            const h = pill.offsetHeight;
            if (h > 0) wrap.style.setProperty('--minion-h', h + 'px');
        });
    }

    function _runMinionDropQueue(parentTaskId) {
        const state = _minionDropQueue.get(parentTaskId);
        if (!state || state.running) return;
        if (state.queue.length === 0) return;
        state.running = true;
        const dropOne = () => {
            const next = state.queue.shift();
            if (!next) {
                state.running = false;
                return;
            }
            _spawnMinionPill(parentTaskId, next.taskId, next.query);
            setTimeout(dropOne, MINION_DROP_STAGGER_MS);
        };
        dropOne();
    }

    window.cliMinionStart = (parentTaskId, taskId, query) => {
        console.log('[minion] start', parentTaskId, taskId, query);
        if (!parentTaskId || !taskId) return;
        if (!_minionDropQueue.has(parentTaskId)) {
            _minionDropQueue.set(parentTaskId, { queue: [], running: false });
        }
        _minionDropQueue.get(parentTaskId).queue.push({ taskId, query });
        _runMinionDropQueue(parentTaskId);
        // Mark parent as having minions and arm the idle filler watcher. If the
        // parent goes silent for FILLER_IDLE_MS, filler phrases start streaming.
        const fs = _ensureFiller(parentTaskId);
        fs.hasMinion = true;
        _scheduleFillerStart(parentTaskId);
    };

    // Stream a line from a running minion's stdout/stderr into its pill body.
    // Reuses the parent-pill word-pagination runner so minion output looks identical
    // to CLI agent output — same word-by-word fade, same per-page hold.
    window.cliMinionLine = (taskId, line, stream) => {
        const pill = _findMinionPill(taskId);
        if (!pill) return;
        const text = line == null ? '' : String(line);
        if (text.trim() === '') return;  // skip blanks so pill body never flashes empty
        const runner = _getRunner(pill);
        runner.queue.push({ text, stream });
        _pumpCliRunner(pill, runner);
    };

    // Web-loading visual on a pill: when the parent CLI agent (or any pill that owns
    // the web tool) starts a web search, flip the pill into web-loading mode. CSS
    // hides the streamed output and shows a clean "web" + 3 pulsing dots indicator.
    // Triggered from the marker bridge so it works for piped CLI subprocesses
    // (which can't fire web_callback directly to the frontend).
    window.cliPillWebLoadingStart = (taskId) => {
        const pill = findCliPill(taskId);
        if (!pill) return;
        pill.classList.add('web-loading');
        const eng = _engineForPill(pill);
        if (eng) eng.setShape('globe');
        _startWebFiller(taskId);
    };
    window.cliPillWebLoadingEnd = (taskId) => {
        const pill = findCliPill(taskId);
        if (!pill) return;
        pill.classList.remove('web-loading');
        const eng = _engineForPill(pill);
        if (eng) eng.setShape('loader');
        _stopWebFiller(taskId);
    };

    window.cliMinionEnd = (taskId, status, summary) => {
        console.log('[minion] end', taskId, status, summary);
        const pill = _findMinionPill(taskId);
        if (!pill) return;
        const finalStatus = status || 'complete';
        pill.dataset.status = finalStatus;
        pill.classList.add('complete');
        // Minion tick stays until absorb cascade removes the wrapper — no
        // sibling-wait + 1s fade like CLI parent pills get.
        const eng = _engineForPill(pill);
        if (eng && finalStatus === 'complete') eng.setShape('tick');

        // Wait for ALL siblings (same parent) to complete, then cascade absorb
        // bottom-to-top. We re-check on each end event — last one tips the cascade.
        const parentId = pill.dataset.parentTaskId;
        const siblings = _siblingMinions(parentId);
        const allComplete = siblings.length > 0
            && siblings.every(s => s.classList.contains('complete'));
        if (!allComplete) return;

        const reversed = siblings.slice().reverse();  // bottom-most absorbed first
        setTimeout(() => {
            reversed.forEach((s, i) => {
                setTimeout(() => {
                    if (!s.isConnected) return;
                    // Drive the absorb on the wrapper so its height collapses in
                    // sync with the inner pill's translateY → -100%. Removing the
                    // wrapper takes the pill with it.
                    const wrap = s.parentElement && s.parentElement.classList.contains('cli-minion-wrap')
                        ? s.parentElement
                        : s;
                    wrap.classList.add('absorbing');
                    wrap.addEventListener('animationend', (ev) => {
                        // Both wrapper and inner pill fire animationend; only act
                        // on the wrapper's own height animation so we don't remove
                        // mid-flight from the inner pill's transform animation.
                        if (ev.target !== wrap) return;
                        // Free the engine before the DOM goes — drops it from the
                        // shared rAF loop and lets the canvas GC.
                        const innerPill = wrap.querySelector('.cli-pill.minion');
                        _detachEngine(innerPill);
                        if (wrap.isConnected) wrap.remove();
                    });
                }, i * MINION_ABSORB_STAGGER_MS);
            });
            // Drop the per-parent drop queue state — the next batch (if any)
            // starts fresh.
            _minionDropQueue.delete(parentId);
            // Batch is done — minions have all completed and are absorbing.
            // Kill any active/pending filler so the parent pill doesn't keep
            // muttering jokes after its children are gone.
            _stopFiller(parentId);
            _fillerState.delete(parentId);
        }, MINION_ABSORB_DELAY_MS);
    };
});
