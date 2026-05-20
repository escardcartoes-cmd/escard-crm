from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_required
import database
import models.sdr_evolutivo as sdr_evo_mod
from models.usuario import require_perfil

sdr_evolutivo_bp = Blueprint('sdr_evolutivo', __name__)


def _tid() -> int:
    return int(session.get("tenant_id") or 1)


@sdr_evolutivo_bp.route("/sdr-evolutivo")
@login_required
@require_perfil('gerente')
def sdr_evolutivo_dashboard():
    db = database.get_connection()
    tid = _tid()
    config = sdr_evo_mod.get_sdr_evolutivo_config(db, tid)

    def _count(sql, params=()):
        try:
            return db.execute(sql, params).fetchone()["n"] or 0
        except Exception:
            return 0

    leads_aprovados  = _count("SELECT COUNT(DISTINCT empresa_id) AS n FROM cadencias WHERE tenant_id=?", (tid,))
    cadencias_criadas = _count("SELECT COUNT(*) AS n FROM cadencias WHERE tenant_id=?", (tid,))
    ecosistema_leads  = _count("SELECT COUNT(*) AS n FROM empresas WHERE tenant_id=? AND status IN ('prospect','importado')", (tid,))
    eventos_radar     = _count("SELECT COUNT(*) AS n FROM radar_intent WHERE tenant_id=?", (tid,))

    db.close()
    return render_template("sdr_evolutivo/dashboard.html",
                           config=config,
                           leads_aprovados=leads_aprovados,
                           cadencias_criadas=cadencias_criadas,
                           ecosistema_leads=ecosistema_leads,
                           eventos_radar=eventos_radar)


@sdr_evolutivo_bp.route("/sdr-evolutivo/executar", methods=["POST"])
@login_required
@require_perfil('gerente')
def sdr_evolutivo_executar():
    try:
        db = database.get_connection()
        config = sdr_evo_mod.get_sdr_evolutivo_config(db, _tid())
        config["tenant_id"] = _tid()
        db.close()

        stats = sdr_evo_mod.executar_sdr_evolutivo(config, _tid())

        flash(f"SDR Evolutivo executado! {stats['leads_aprovados']} leads aprovados, {stats['cadencias_criadas']} cadências criadas.", "success")
        return redirect(url_for("sdr_evolutivo.sdr_evolutivo_dashboard"))
    except Exception as e:
        flash(f"Erro ao executar SDR Evolutivo: {str(e)}", "danger")
        return redirect(url_for("sdr_evolutivo.sdr_evolutivo_dashboard"))


@sdr_evolutivo_bp.route("/sdr-evolutivo/configurar", methods=["GET", "POST"])
@login_required
@require_perfil('gerente')
def sdr_evolutivo_configurar():
    db = database.get_connection()

    if request.method == "POST":
        try:
            score_min = int(request.form.get("score_prontidao_minimo", 8))
            max_leads = int(request.form.get("max_leads_por_execucao", 20))
            usar_radar = 1 if request.form.get("usar_radar_intent") else 0
            usar_ecosistema = 1 if request.form.get("usar_ecosistema") else 0
            pitch_adaptativo = 1 if request.form.get("pitch_adaptativo") else 0

            db.execute("""
                INSERT OR REPLACE INTO sdr_evolutivo_config
                (tenant_id, score_prontidao_minimo, max_leads_por_execucao,
                 usar_radar_intent, usar_ecosistema, pitch_adaptativo)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (_tid(), score_min, max_leads, usar_radar, usar_ecosistema, pitch_adaptativo))
            db.commit()
            db.close()
            flash("Configurações salvas com sucesso!", "success")
            return redirect(url_for("sdr_evolutivo.sdr_evolutivo_dashboard"))
        except Exception as e:
            flash(f"Erro ao salvar configurações: {str(e)}", "danger")

    config = sdr_evo_mod.get_sdr_evolutivo_config(db, _tid())
    db.close()
    return render_template("sdr_evolutivo/configurar.html", config=config)


@sdr_evolutivo_bp.route("/sdr-evolutivo/radar")
@login_required
@require_perfil('gerente')
def sdr_evolutivo_radar():
    db = database.get_connection()
    try:
        eventos = db.execute("""
            SELECT * FROM radar_intent
            WHERE tenant_id = ?
            ORDER BY criado_em DESC
            LIMIT 50
        """, (_tid(),)).fetchall()
    except Exception:
        eventos = []
    finally:
        db.close()
    return render_template("sdr_evolutivo/radar.html", eventos=eventos)
