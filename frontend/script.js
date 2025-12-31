const API_BASE_URL = 'http://localhost:8000';
let currentSessionId = null;
let currentStoryData = null;

// DOM Elements
const generateBtn = document.getElementById('generateBtn');
const promptInput = document.getElementById('prompt');
const charCounter = document.getElementById('charCounter');
const submitFeedbackBtn = document.getElementById('submitFeedbackBtn');
const doneBtn = document.getElementById('doneBtn');
const feedbackInput = document.getElementById('feedback');
const generateTitleBtn = document.getElementById('generateTitleBtn');
const extractMoralBtn = document.getElementById('extractMoralBtn');
const copyStoryBtn = document.getElementById('copyStoryBtn');
const exportStoryBtn = document.getElementById('exportStoryBtn');
const clearSessionBtn = document.getElementById('clearSessionBtn');
const quickFeedbackBtns = document.querySelectorAll('.quick-btn');
const storyContent = document.getElementById('storyContent');
const historyList = document.getElementById('historyList');
const sessionInfo = document.getElementById('sessionInfo');
const sessionIdSpan = document.getElementById('sessionId');
const revisionCountSpan = document.getElementById('revisionCount');
const progressFill = document.getElementById('progressFill');
const revisionStats = document.getElementById('revisionStats');
const feedbackSection = document.getElementById('feedbackSection');
const feedbackMessage = document.getElementById('feedbackMessage');
const enhancementSection = document.getElementById('enhancementSection');
const titleResult = document.getElementById('titleResult');
const titleText = document.getElementById('titleText');
const moralResult = document.getElementById('moralResult');
const moralText = document.getElementById('moralText');
const titleStatus = document.getElementById('titleStatus');
const moralStatus = document.getElementById('moralStatus');
const statusText = document.getElementById('statusText');
const loadingSpinner = document.getElementById('loadingSpinner');
const statusBar = document.getElementById('statusBar');

// Character counter for prompt
promptInput.addEventListener('input', () => {
    const length = promptInput.value.length;
    charCounter.textContent = `${length}/500`;
    if (length > 400) {
        charCounter.style.color = '#f5576c';
    } else if (length > 300) {
        charCounter.style.color = '#fee140';
    } else {
        charCounter.style.color = 'var(--text-secondary)';
    }
});

// Quick feedback buttons
quickFeedbackBtns.forEach(btn => {
    btn.addEventListener('click', () => {
        feedbackInput.value = btn.dataset.feedback;
        feedbackInput.focus();
        showToast('Feedback suggestion added!', 'info');
    });
});

// Show toast notification
function showToast(message, type = 'info') {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = `toast ${type}`;
    toast.classList.add('show');
    
    setTimeout(() => {
        toast.classList.remove('show');
    }, 3000);
}

// Update UI state
function setLoading(isLoading) {
    if (isLoading) {
        loadingSpinner.style.display = 'block';
        statusText.textContent = 'Generating magic...';
        generateBtn.disabled = true;
        submitFeedbackBtn.disabled = true;
        doneBtn.disabled = true;
        generateTitleBtn.disabled = true;
        extractMoralBtn.disabled = true;
        copyStoryBtn.disabled = true;
        exportStoryBtn.disabled = true;
    } else {
        loadingSpinner.style.display = 'none';
        generateBtn.disabled = false;
        submitFeedbackBtn.disabled = false;
        doneBtn.disabled = false;
        copyStoryBtn.disabled = false;
        exportStoryBtn.disabled = false;
        updateButtonStates();
    }
}

// Update button states based on current data
function updateButtonStates() {
    if (currentStoryData) {
        if (currentStoryData.title && currentStoryData.title !== "None") {
            generateTitleBtn.disabled = true;
            titleStatus.innerHTML = '<i class="fas fa-check"></i>';
            titleStatus.style.color = '#43e97b';
        } else {
            generateTitleBtn.disabled = false;
            titleStatus.innerHTML = '<i class="fas fa-plus"></i>';
            titleStatus.style.color = '';
        }
        
        if (currentStoryData.moral && currentStoryData.moral !== "None") {
            extractMoralBtn.disabled = true;
            moralStatus.innerHTML = '<i class="fas fa-check"></i>';
            moralStatus.style.color = '#43e97b';
        } else {
            extractMoralBtn.disabled = false;
            moralStatus.innerHTML = '<i class="fas fa-plus"></i>';
            moralStatus.style.color = '';
        }
    }
}

// Display story content with enhanced formatting
function displayStory(story) {
    if (!story || story.trim() === '') {
        storyContent.innerHTML = `
            <div class="empty-state">
                <i class="fas fa-feather"></i>
                <h3>Your Story Awaits</h3>
                <p>Enter a prompt above to begin your creative journey. Watch as your story unfolds and evolves with each refinement.</p>
            </div>
        `;
    } else {
        // Format the story with paragraph breaks and styling
        const paragraphs = story.split('\n\n').filter(p => p.trim());
        const formattedStory = paragraphs.map(paragraph => {
            if (paragraph.startsWith('# ')) {
                return `<h3 class="story-heading">${paragraph.substring(2)}</h3>`;
            } else if (paragraph.startsWith('> ')) {
                return `<blockquote class="story-quote">${paragraph.substring(2)}</blockquote>`;
            } else {
                return `<p>${paragraph.replace(/\n/g, '<br>')}</p>`;
            }
        }).join('');
        
        storyContent.innerHTML = formattedStory;
        storyContent.scrollTop = 0; // Scroll to top
    }
}

// Update history timeline
function updateHistory(history) {
    historyList.innerHTML = '';
    
    if (history && history.length > 0) {
        history.forEach((item, index) => {
            const timelineItem = document.createElement('div');
            timelineItem.className = 'timeline-item';
            timelineItem.style.marginBottom = '1rem';
            timelineItem.style.position = 'relative';
            timelineItem.style.paddingLeft = '2rem';
            
            // Determine icon and color based on content
            let icon = 'edit';
            let color = '#667eea';
            
            if (item.includes('Initial draft')) {
                icon = 'sparkles';
                color = '#fa709a';
            } else if (item.toLowerCase().includes('title')) {
                icon = 'crown';
                color = '#fee140';
            } else if (item.toLowerCase().includes('moral')) {
                icon = 'heart-circle-check';
                color = '#43e97b';
            } else if (item.includes('Revision')) {
                icon = 'sync-alt';
                color = '#4facfe';
            }
            
            timelineItem.innerHTML = `
                <div class="timeline-marker" style="position: absolute; left: 0; top: 0; width: 20px; height: 20px; background: ${color}; border-radius: 50%; display: flex; align-items: center; justify-content: center; color: white;">
                    <i class="fas fa-${icon}" style="font-size: 0.7rem;"></i>
                </div>
                <div class="timeline-content" style="background: white; padding: 0.75rem 1rem; border-radius: 8px; border-left: 3px solid ${color};">
                    <div style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.25rem;">
                        <i class="fas fa-${icon}" style="color: ${color};"></i>
                        <span style="font-weight: 500;">${item}</span>
                    </div>
                    <small style="color: var(--text-light); font-size: 0.8rem;">
                        <i class="far fa-clock"></i> Just now
                    </small>
                </div>
            `;
            
            historyList.appendChild(timelineItem);
        });
        
        // Update revision stats
        const revisions = history.filter(item => item.includes('Revision')).length;
        revisionStats.textContent = `${revisions} Revision${revisions !== 1 ? 's' : ''}`;
    } else {
        historyList.innerHTML = `
            <div class="timeline-empty">
                <i class="fas fa-seedling"></i>
                <p>Your story's evolution will appear here</p>
            </div>
        `;
        revisionStats.textContent = '0 Revisions';
    }
}

// Update enhancement results
function updateEnhancements(title, moral) {
    if (title && title !== "None") {
        titleText.textContent = title;
        titleResult.style.display = 'block';
    } else {
        titleResult.style.display = 'none';
    }
    
    if (moral && moral !== "None") {
        moralText.textContent = moral;
        moralResult.style.display = 'block';
    } else {
        moralResult.style.display = 'none';
    }
    
    updateButtonStates();
}

// Update progress bar
function updateProgress(revisionCount) {
    const progress = (revisionCount / 3) * 100;
    progressFill.style.width = `${Math.min(progress, 100)}%`;
    revisionCountSpan.textContent = `${revisionCount}/3`;
    
    // Update progress bar color based on revision count
    if (revisionCount === 3) {
        progressFill.style.background = 'var(--warning-gradient)';
    } else if (revisionCount >= 2) {
        progressFill.style.background = 'var(--success-gradient)';
    } else {
        progressFill.style.background = 'var(--accent-gradient)';
    }
}

// Show/hide sections based on state
function updateUISections(requiresFeedback, storyComplete, hasStory) {
    if (hasStory) {
        sessionInfo.style.display = 'block';
        enhancementSection.style.display = 'block';
        
        if (requiresFeedback) {
            feedbackSection.style.display = 'block';
            statusText.textContent = 'Awaiting your feedback...';
        } else {
            feedbackSection.style.display = 'none';
            statusText.textContent = 'Story ready for enhancements!';
        }
        
        // Update status bar color
        if (storyComplete) {
            statusBar.style.background = 'var(--success-gradient)';
            statusText.textContent = 'Story masterpiece completed! 🎉';
        } else if (requiresFeedback) {
            statusBar.style.background = 'var(--warning-gradient)';
        } else {
            statusBar.style.background = 'var(--primary-gradient)';
        }
    } else {
        sessionInfo.style.display = 'none';
        enhancementSection.style.display = 'none';
        feedbackSection.style.display = 'none';
    }
}

// Start new story
async function startStory() {
    const prompt = promptInput.value.trim();
    if (!prompt) {
        showToast('✨ Please enter a story prompt to begin your journey', 'error');
        promptInput.focus();
        return;
    }

    if (prompt.length > 500) {
        showToast('Prompt should be less than 500 characters', 'error');
        return;
    }

    setLoading(true);
    statusText.textContent = 'Crafting your story...';

    try {
        const response = await fetch(`${API_BASE_URL}/api/start`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ prompt })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to start story generation');
        }

        const data = await response.json();
        currentSessionId = data.session_id;
        currentStoryData = data;
        
        // Update UI
        sessionIdSpan.textContent = currentSessionId;
        updateProgress(data.revision_count);
        displayStory(data.story);
        updateHistory(data.history);
        updateEnhancements(data.title, data.moral);
        updateUISections(data.requires_feedback, data.story_complete, true);
        
        if (data.requires_feedback) {
            feedbackMessage.textContent = data.message || 'Your story is taking shape! How would you like to refine it?';
            feedbackInput.focus();
            showToast('Story generated! Time for refinement ✨', 'success');
        } else {
            showToast('Story masterpiece created! 🎨', 'success');
        }
        
    } catch (error) {
        showToast(`Oops! ${error.message}`, 'error');
        console.error('Error:', error);
        statusText.textContent = 'Something went wrong';
    } finally {
        setLoading(false);
    }
}

// Submit feedback
async function submitFeedback() {
    const feedback = feedbackInput.value.trim();
    if (!feedback) {
        showToast('Please enter your feedback to refine the story', 'error');
        feedbackInput.focus();
        return;
    }

    if (!currentSessionId) {
        showToast('No active story session found', 'error');
        return;
    }

    setLoading(true);
    statusText.textContent = 'Applying your creative touch...';

    try {
        const response = await fetch(`${API_BASE_URL}/api/feedback`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                session_id: currentSessionId,
                feedback: feedback
            })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to apply feedback');
        }

        const data = await response.json();
        currentStoryData = data;
        
        // Update UI
        updateProgress(data.revision_count);
        displayStory(data.story);
        updateHistory(data.history);
        updateEnhancements(data.title, data.moral);
        updateUISections(data.requires_feedback, data.story_complete, true);
        feedbackInput.value = '';
        
        if (data.requires_feedback) {
            feedbackMessage.textContent = data.message || 'Great refinement! Want to polish it further?';
            feedbackInput.focus();
            showToast('Story refined! Ready for another touch? ✨', 'success');
        } else {
            showToast('Story perfected! Ready for enhancements 🎉', 'success');
        }
        
    } catch (error) {
        showToast(`Oops! ${error.message}`, 'error');
        console.error('Error:', error);
        statusText.textContent = 'Something went wrong';
    } finally {
        setLoading(false);
    }
}

// Mark story as done
async function markAsDone() {
    if (!currentSessionId) {
        showToast('No active story session found', 'error');
        return;
    }

    setLoading(true);
    statusText.textContent = 'Finalizing your masterpiece...';

    try {
        const response = await fetch(`${API_BASE_URL}/api/feedback`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                session_id: currentSessionId,
                feedback: 'done'
            })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to finalize story');
        }

        const data = await response.json();
        currentStoryData = data;
        
        // Update UI
        updateProgress(data.revision_count);
        displayStory(data.story);
        updateHistory(data.history);
        updateEnhancements(data.title, data.moral);
        updateUISections(data.requires_feedback, data.story_complete, true);
        showToast('Story masterpiece completed! Time for enhancements 🏆', 'success');
        
    } catch (error) {
        showToast(`Oops! ${error.message}`, 'error');
        console.error('Error:', error);
        statusText.textContent = 'Something went wrong';
    } finally {
        setLoading(false);
    }
}

// Generate title
async function generateTitle() {
    if (!currentSessionId) {
        showToast('No active story session found', 'error');
        return;
    }

    if (!storyContent.textContent || storyContent.textContent.includes('empty-state')) {
        showToast('Please generate a story first', 'warning');
        return;
    }

    setLoading(true);
    statusText.textContent = 'Crafting the perfect title...';

    try {
        const response = await fetch(`${API_BASE_URL}/api/enhance`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                session_id: currentSessionId,
                enhancement_type: 'title'
            })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to generate title');
        }

        const data = await response.json();
        currentStoryData = data;
        
        // Update UI
        updateEnhancements(data.title, data.moral);
        updateHistory(data.history);
        updateUISections(data.requires_feedback, data.story_complete, true);
        showToast('Title crafted perfectly! ✨', 'success');
        
    } catch (error) {
        showToast(`Oops! ${error.message}`, 'error');
        console.error('Error:', error);
        statusText.textContent = 'Something went wrong';
    } finally {
        setLoading(false);
    }
}

// Extract moral
async function extractMoral() {
    if (!currentSessionId) {
        showToast('No active story session found', 'error');
        return;
    }

    if (!storyContent.textContent || storyContent.textContent.includes('empty-state')) {
        showToast('Please generate a story first', 'warning');
        return;
    }

    setLoading(true);
    statusText.textContent = 'Discovering the story\'s essence...';

    try {
        const response = await fetch(`${API_BASE_URL}/api/enhance`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                session_id: currentSessionId,
                enhancement_type: 'moral'
            })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to extract moral');
        }

        const data = await response.json();
        currentStoryData = data;
        
        // Update UI
        updateEnhancements(data.title, data.moral);
        updateHistory(data.history);
        updateUISections(data.requires_feedback, data.story_complete, true);
        showToast('Story essence discovered! 💫', 'success');
        
    } catch (error) {
        showToast(`Oops! ${error.message}`, 'error');
        console.error('Error:', error);
        statusText.textContent = 'Something went wrong';
    } finally {
        setLoading(false);
    }
}

// Copy story to clipboard
copyStoryBtn.addEventListener('click', async () => {
    if (!currentStoryData || !currentStoryData.story) {
        showToast('No story to copy', 'warning');
        return;
    }

    try {
        await navigator.clipboard.writeText(currentStoryData.story);
        showToast('Story copied to clipboard! 📋', 'success');
    } catch (error) {
        showToast('Failed to copy story', 'error');
    }
});

// Export story
exportStoryBtn.addEventListener('click', () => {
    if (!currentStoryData || !currentStoryData.story) {
        showToast('No story to export', 'warning');
        return;
    }

    const storyContent = `
StoryCraft AI - ${currentStoryData.title || 'Untitled Story'}
${'='.repeat(50)}

${currentStoryData.story}

${'='.repeat(50)}
Session: ${currentStoryData.session_id}
Revisions: ${currentStoryData.revision_count}
Created: ${new Date().toLocaleString()}

${currentStoryData.title ? `Title: ${currentStoryData.title}` : ''}
${currentStoryData.moral ? `Theme: ${currentStoryData.moral}` : ''}
    `.trim();

    const blob = new Blob([storyContent], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `storycraft-${currentSessionId || 'story'}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    
    showToast('Story exported successfully! 📥', 'success');
});

// Clear session
clearSessionBtn.addEventListener('click', () => {
    if (currentSessionId) {
        if (confirm('Start a new creative session? Your current story will be saved.')) {
            currentSessionId = null;
            currentStoryData = null;
            promptInput.value = '';
            charCounter.textContent = '0/500';
            displayStory('');
            updateHistory([]);
            updateEnhancements(null, null);
            updateProgress(0);
            updateUISections(false, false, false);
            sessionIdSpan.textContent = '-';
            promptInput.focus();
            showToast('New session ready! What will you create? ✨', 'info');
        }
    } else {
        promptInput.value = '';
        promptInput.focus();
        showToast('Ready for your next masterpiece!', 'info');
    }
});

// Event Listeners
generateBtn.addEventListener('click', startStory);
submitFeedbackBtn.addEventListener('click', submitFeedback);
doneBtn.addEventListener('click', markAsDone);
generateTitleBtn.addEventListener('click', generateTitle);
extractMoralBtn.addEventListener('click', extractMoral);

// Allow Enter key to submit prompt (but Shift+Enter for new line)
promptInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        startStory();
    }
});

// Allow Enter key to submit feedback (but Shift+Enter for new line)
feedbackInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        submitFeedback();
    }
});

// Check if API is available on load
async function checkAPI() {
    try {
        const response = await fetch(`${API_BASE_URL}/health`);
        if (response.ok) {
            showToast('StoryCraft AI is ready to create magic! ✨', 'success');
            statusText.textContent = 'Connected & ready to create';
        }
    } catch (error) {
        console.warn('API not available:', error);
        showToast('StoryCraft AI is warming up...', 'warning');
        statusText.textContent = 'Connecting to creative engine...';
    }
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    promptInput.focus();
    checkAPI();
    
    // Animate hero elements
    setTimeout(() => {
        document.querySelector('.hero-title').style.opacity = '1';
        document.querySelector('.hero-description').style.opacity = '1';
    }, 100);
    
    // Add floating animation to stats
    const stats = document.querySelectorAll('.stat-item');
    stats.forEach((stat, index) => {
        stat.style.animationDelay = `${index * 0.2}s`;
        stat.classList.add('floating');
    });
});