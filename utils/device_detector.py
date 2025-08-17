"""
Device detection utility for serving different templates to mobile and desktop users
"""
import re
from flask import request

def is_mobile_device():
    """
    Detect if the user is on a mobile device based on User-Agent
    Returns True for mobile devices, False for desktop
    """
    user_agent = request.headers.get('User-Agent', '').lower()
    
    mobile_keywords = [
        'mobile', 'android', 'iphone', 'ipad', 'ipod', 'blackberry', 
        'windows phone', 'webos', 'opera mini', 'palm', 'symbian'
    ]
    
    return any(keyword in user_agent for keyword in mobile_keywords)

def get_template_path(base_template_name):
    """
    Return the appropriate template path based on device type
    Args:
        base_template_name: e.g., 'dashboard.html'
    Returns:
        'mobile/dashboard.html' for mobile devices
        'dashboard.html' for desktop devices
    """
    if is_mobile_device():
        return f'mobile/{base_template_name}'
    else:
        return base_template_name