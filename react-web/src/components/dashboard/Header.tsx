/**
 * Dashboard Header Component with AWS branding and user info
 */

import React from 'react';
import { useAuth } from '../../contexts/AuthContext';
import { Button } from '../common/Button';
import './Header.css';

export interface HeaderProps {
  className?: string;
}

export const Header: React.FC<HeaderProps> = ({ className = '' }) => {
  const { user, signOut } = useAuth();

  const handleSignOut = async () => {
    try {
      await signOut();
    } catch (error) {
      console.error('Sign out error:', error);
    }
  };

  return (
    <header className={`dashboard-header ${className}`}>
      <div className="dashboard-header__container">
        {/* Left side - Logo and Title */}
        <div className="dashboard-header__brand">
          <div className="dashboard-header__logos">
            <img
              src="https://d0.awsstatic.com/logos/powered-by-aws.png"
              alt="AWS Logo"
              className="dashboard-header__logo dashboard-header__logo--aws"
            />
            <img
              src="https://upload.wikimedia.org/wikipedia/commons/thumb/7/7d/Intel_logo_%282006-2020%29.svg/200px-Intel_logo_%282006-2020%29.svg.png"
              alt="Intel Logo"
              className="dashboard-header__logo dashboard-header__logo--intel"
            />
            <img
              src="https://assets.ubuntu.com/v1/29985a98-ubuntu-logo32.png"
              alt="Ubuntu/Canonical Logo"
              className="dashboard-header__logo dashboard-header__logo--ubuntu"
            />
          </div>
          <div className="dashboard-header__title-group">
            <h1 className="dashboard-header__title">Computer Vision at Edge</h1>
            <p className="dashboard-header__subtitle">
              Powered by AWS • Intel OpenVINO • Canonical Ubuntu Core
            </p>
          </div>
        </div>

        {/* Right side - User info and actions */}
        <div className="dashboard-header__actions">
          {user && (
            <div className="dashboard-header__user">
              <div className="dashboard-header__user-info">
                <span className="dashboard-header__user-name">
                  {user.email || user.username}
                </span>
                <span className="dashboard-header__user-role">
                  Authenticated User
                </span>
              </div>
              <div className="dashboard-header__user-avatar">
                {(user.email || user.username).charAt(0).toUpperCase()}
              </div>
            </div>
          )}

          <Button
            variant="secondary"
            size="sm"
            onClick={handleSignOut}
            className="dashboard-header__sign-out"
          >
            Sign Out
          </Button>
        </div>
      </div>
    </header>
  );
};
