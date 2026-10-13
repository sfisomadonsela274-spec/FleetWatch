import express from 'express';
import jwt from 'jsonwebtoken';
import { z } from 'zod';
import { CONFIG } from '../config.js';
import { store } from '../db/store.js';

const router = express.Router();

const SignInSchema = z.object({
  identifier: z.string().min(3),
  password: z.string().min(4)
});

const SignUpSchema = z.object({
  fullName: z.string().min(2),
  companyName: z.string().min(2),
  email: z.string().email(),
  mobile: z.string().min(9),
  fleetSize: z.string(),
  corridor: z.string(),
  password: z.string().min(6)
});

// Sign In
router.post('/signin', (req, res) => {
  try {
    const data = SignInSchema.parse(req.body);
    const token = jwt.sign(
      {
        userId: store.user.id,
        tenantId: store.tenant.id,
        name: store.user.name,
        role: store.user.role
      },
      CONFIG.JWT_SECRET,
      { expiresIn: '24h' }
    );

    return res.json({
      success: true,
      token,
      user: store.user,
      tenant: store.tenant
    });
  } catch (err) {
    return res.status(400).json({ success: false, error: err.errors || err.message });
  }
});

// Sign Up
router.post('/signup', (req, res) => {
  try {
    const data = SignUpSchema.parse(req.body);
    const newUser = {
      id: `user-${Date.now()}`,
      tenantId: `tenant-${Date.now()}`,
      name: data.fullName,
      role: 'Fleet Manager',
      email: data.email,
      mobile: data.mobile,
      company: data.companyName,
      avatar: 'https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&q=80&w=150'
    };

    const token = jwt.sign(
      {
        userId: newUser.id,
        tenantId: newUser.tenantId,
        name: newUser.name,
        role: newUser.role
      },
      CONFIG.JWT_SECRET,
      { expiresIn: '24h' }
    );

    return res.json({
      success: true,
      token,
      user: newUser,
      tenant: {
        id: newUser.tenantId,
        name: data.companyName,
        primaryCorridor: data.corridor
      }
    });
  } catch (err) {
    return res.status(400).json({ success: false, error: err.errors || err.message });
  }
});

// Instant 1-Click CEO Demo Login
router.post('/ceo-demo', (req, res) => {
  const token = jwt.sign(
    {
      userId: store.user.id,
      tenantId: store.tenant.id,
      name: store.user.name,
      role: store.user.role
    },
    CONFIG.JWT_SECRET,
    { expiresIn: '24h' }
  );

  return res.json({
    success: true,
    token,
    user: store.user,
    tenant: store.tenant
  });
});

// Verify Current User
router.get('/me', (req, res) => {
  const authHeader = req.headers.authorization;
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    return res.status(401).json({ success: false, error: 'Unauthorized' });
  }

  const token = authHeader.split(' ')[1];
  try {
    const decoded = jwt.verify(token, CONFIG.JWT_SECRET);
    return res.json({
      success: true,
      user: store.user,
      tenant: store.tenant,
      tokenPayload: decoded
    });
  } catch (err) {
    return res.status(401).json({ success: false, error: 'Invalid or expired token' });
  }
});

export default router;
