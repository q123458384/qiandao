#!/usr/bin/env python
# -*- encoding: utf-8 -*-
# vim: set et sw=4 ts=4 sts=4 ff=unix fenc=utf8:
# Author: Binux<i@binux.me>
#         http://binux.me
# Created on 2014-08-08 20:38:51

import re
import time
import base64
import umsgpack
from tornado import gen
from tornado.ioloop import IOLoop

import config
from base import *
from libs import utils

class LoginHandler(BaseHandler):
    def get(self):
        if self.current_user:
            self.redirect('/my/')
            return
        return self.render('login.html')

    def post(self):
        email = self.get_argument('email')
        password = self.get_argument('password')
        if not email or not password:
            self.render('login.html', password_error=u'请输入用户名和密码', email=email)
            return

        if self.db.user.challenge(email, password):
            user = self.db.user.get(email=email, fields=('id', 'email', 'nickname', 'role'))
            if not user:
                self.render('login.html', password_error=u'不存在此邮箱或密码错误', email=email)
                return

            setcookie = dict(
                    expires_days=config.cookie_days,
                    httponly=True,
                    )
            if config.https:
                setcookie['secure'] = True
            self.set_secure_cookie('user', umsgpack.packb(user), **setcookie)
            self.db.user.mod(user['id'], atime=time.time(), aip=self.ip2int)
            
            next = self.get_argument('next', '/my/')
            self.redirect(next)
        else:
            self.evil(+5)
            self.render('login.html', password_error=u'不存在此邮箱或密码错误', email=email)

class LogoutHandler(BaseHandler):
    def get(self):
        self.clear_all_cookies()
        self.redirect('/')

class RegisterHandler(BaseHandler):
    def get(self):
        if self.current_user:
            self.redirect('/my/')
            return
        return self.render('register.html')

    def post(self):
        self.evil(+5)

        email = self.get_argument('email')
        password = self.get_argument('password')

        if not email:
            self.render('register.html', email_error=u'请输入邮箱')
            return
        if email.count('@') != 1 or email.count('.') == 0:
            self.render('register.html', email_error=u'邮箱格式不正确')
            return
        if len(password) < 6:
            self.render('register.html', password_error=u'密码需要大于6位', email=email)
            return

        try:
            self.db.user.add(email=email, password=password, ip=self.ip2int)
        except self.db.user.DeplicateUser as e:
            self.evil(+3)
            self.render('register.html', email_error=u'email地址已注册')
            return
        user = self.db.user.get(email=email, fields=('id', 'email', 'nickname', 'role'))

        setcookie = dict(
                expires_days=config.cookie_days,
                httponly=True,
                )
        if config.https:
            setcookie['secure'] = True
        self.set_secure_cookie('user', umsgpack.packb(user), **setcookie)

        next = self.get_argument('next', '/my/')
        self.redirect(next)
        future = self.send_mail(user)
        if future:
            IOLoop.current().add_future(future, lambda x: x)

    def send_mail(self, user):
        verified_code = [user['email'], time.time()]
        verified_code = self.db.user.encrypt(user['id'], verified_code)
        verified_code = self.db.user.encrypt(0, [user['id'], verified_code])
        verified_code = base64.b64encode(verified_code)
        future = utils.send_mail(to=user['email'], subject=u"欢迎注册 签到平台", html=u"""
                <table style="width:99.8%%;height:99.8%%"><tbody><tr><td style=" background:#fafafa url(#) "><div style="border-radius:10px;font-size:13px;color:#555;width:666px;font-family:'Century Gothic','Trebuchet MS','Hiragino Sans GB','微软雅黑','Microsoft Yahei',Tahoma,Helvetica,Arial,SimSun,sans-serif;margin:50px auto;border:1px solid #eee;max-width:100%%;background:#fff repeating-linear-gradient(-45deg,#fff,#fff 1.125rem,transparent 1.125rem,transparent 2.25rem);box-shadow:0 1px 5px rgba(0,0,0,.15)"><div style="width:100%%;background:#49BDAD;color:#fff;border-radius:10px 10px 0 0;background-image:-moz-linear-gradient(0deg,#43c6b8,#ffd1f4);background-image:-webkit-linear-gradient(0deg,#4831ff,#0497ff);height:66px"><p style="font-size:15px;word-break:break-all;padding:23px 32px;margin:0;background-color:hsla(0,0%%,100%%,.4);border-radius:10px 10px 0 0">&nbsp;[签到平台]&nbsp;&nbsp;http://%s</p></div>
                <div style="margin:40px auto;width:90%%">
                    <p>点击以下链接验证邮箱，当您的签到失败的时候，会自动给您发送通知邮件。</p>
                    <p style="background:#fafafa repeating-linear-gradient(-45deg,#fff,#fff 1.125rem,transparent 1.125rem,transparent 2.25rem);box-shadow:0 2px 5px rgba(0,0,0,.15);margin:20px 0;padding:15px;border-radius:5px;font-size:14px;color:#555"><a href="http://%s/verify/%s">http://%s/verify/%s</a></p>
                    <p>请注意：此邮件由 <a href="http://%s/verify/%s" style="color:#12addb" target="_blank">签到平台</a> 自动发送，请勿直接回复。</p>
                    <p>若此邮件不是您请求的，请忽略并删除！</p>
                </div>
            </div>
        </td>
        </tr>
        </tbody>
        </table>
        """ % (config.domain, config.domain, verified_code, config.domain, verified_code, config.domain, verified_code), async=True)

        def get_result(future):
            try:
                return future.result()
            except Exception as e:
                logging.error(e)

        if future:
            future.add_done_callback(get_result)
        return future

class VerifyHandler(BaseHandler):
    def get(self, code):
        try:
            verified_code = base64.b64decode(code)
            userid, verified_code = self.db.user.decrypt(0, verified_code)
            user = self.db.user.get(userid, fields=('id', 'email', 'email_verified'))
            assert user
            assert not user['email_verified']
            email, time_time = self.db.user.decrypt(userid, verified_code)
            assert time.time() - time_time < 30 * 24 * 60 * 60
            assert user['email'] == email

            self.db.user.mod(userid,
                    email_verified=True,
                    mtime=time.time()
                    )
            self.finish('验证成功')
        except Exception as e:
            self.evil(+5)
            logger.error(e)
            self.set_status(400)
            self.finish('验证失败')


class PasswordResetHandler(BaseHandler):
    def get(self, code):
        if not code:
            return self.render('password_reset_email.html')

        try:
            verified_code = base64.b64decode(code)
            userid, verified_code = self.db.user.decrypt(0, verified_code)
            user = self.db.user.get(userid, fields=('id', 'email', 'mtime'))
            assert user
            mtime, time_time = self.db.user.decrypt(userid, verified_code)
            assert mtime == user['mtime']
            assert time.time() - time_time < 60 * 60
        except Exception as e:
            self.evil(+10)
            logger.error(e)
            self.set_status(400)
            self.finish('Bad Request')
            return

        return self.render('password_reset.html')

    def post(self, code):
        if not code:
            self.evil(+5)

            email = self.get_argument('email')
            if not email:
                return self.render('password_reset_email.html',
                                   email_error=u'请输入邮箱')
            if email.count('@') != 1 or email.count('.') == 0:
                return self.render('password_reset_email.html',
                                   email_error=u'邮箱格式不正确')

            user = self.db.user.get(email=email, fields=('id', 'email', 'mtime', 'nickname', 'role'))
            if user:
                logger.info('password reset: userid=%(id)s email=%(email)s', user)
                future = self.send_mail(user)
                if future:
                    IOLoop.current().add_future(future, lambda x: x)

            return self.finish("如果用户存在，会将发送密码重置邮件到您的邮箱，请注意查收。（如果您没有收到过激活邮件，可能无法也无法收到密码重置邮件）")
        else:
            password = self.get_argument('password')
            if len(password) < 6:
                return self.render('password_reset.html', password_error=u'密码需要大于6位')

            try:
                verified_code = base64.b64decode(code)
                userid, verified_code = self.db.user.decrypt(0, verified_code)
                user = self.db.user.get(userid, fields=('id', 'email', 'mtime', 'email_verified'))
                assert user
                mtime, time_time = self.db.user.decrypt(userid, verified_code)
                assert mtime == user['mtime']
                assert time.time() - time_time < 60 * 60
            except Exception as e:
                self.evil(+10)
                logger.error(e)
                self.set_status(400)
                self.finish('Bad Request')
                return

            self.db.user.mod(userid,
                             password=password,
                             mtime=time.time(),
                             )
            return self.finish("密码重置成功!")

    def send_mail(self, user):
        verified_code = [user['mtime'], time.time()]
        verified_code = self.db.user.encrypt(user['id'], verified_code)
        verified_code = self.db.user.encrypt(0, [user['id'], verified_code])
        verified_code = base64.b64encode(verified_code)

        future = utils.send_mail(to=user['email'], subject=u"签到平台(%s) 密码重置" % (config.domain), html=u"""

        <table style="width:99.8%%;height:99.8%%"><tbody><tr><td style=" background:#fafafa url(#) "><div style="border-radius:10px;font-size:13px;color:#555;width:666px;font-family:'Century Gothic','Trebuchet MS','Hiragino Sans GB','微软雅黑','Microsoft Yahei',Tahoma,Helvetica,Arial,SimSun,sans-serif;margin:50px auto;border:1px solid #eee;max-width:100%%;background:#fff repeating-linear-gradient(-45deg,#fff,#fff 1.125rem,transparent 1.125rem,transparent 2.25rem);box-shadow:0 1px 5px rgba(0,0,0,.15)"><div style="width:100%%;background:#49BDAD;color:#fff;border-radius:10px 10px 0 0;background-image:-moz-linear-gradient(0deg,#43c6b8,#ffd1f4);background-image:-webkit-linear-gradient(0deg,#4831ff,#0497ff);height:66px"><p style="font-size:15px;word-break:break-all;padding:23px 32px;margin:0;background-color:hsla(0,0%%,100%%,.4);border-radius:10px 10px 0 0">&nbsp;[签到平台]&nbsp;&nbsp;http://%s</p></div>
                <div style="margin:40px auto;width:90%%">
                    <p>点击以下链接完成您的密码重置（一小时内有效）。</p>
                    <p style="background:#fafafa repeating-linear-gradient(-45deg,#fff,#fff 1.125rem,transparent 1.125rem,transparent 2.25rem);box-shadow:0 2px 5px rgba(0,0,0,.15);margin:20px 0;padding:15px;border-radius:5px;font-size:14px;color:#555"><a href="http://%s/password_reset/%s">http://%s/password_reset/%s</a></p>
                    <p>请注意：此邮件由 <a href="http://%s/verify/%s" style="color:#12addb" target="_blank">签到平台</a> 自动发送，请勿直接回复。</p>
                    <p>若此邮件不是您请求的，请忽略并删除！</p>
                </div>
            </div>
        </td>
        </tr>
        </tbody>
        </table>

        """ % (config.domain, config.domain, verified_code, config.domain, verified_code, config.domain, verified_code), async=True)

        def get_result(future):
            try:
                return future.result()
            except Exception as e:
                logging.error(e)
        if future:
            future.add_done_callback(get_result)
        return future

handlers = [
        ('/login', LoginHandler),
        ('/logout', LogoutHandler),
        ('/register', RegisterHandler),
        ('/verify/(.*)', VerifyHandler),
        ('/password_reset/?(.*)', PasswordResetHandler),
        ]
