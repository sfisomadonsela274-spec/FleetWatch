// South African Multilingual Driver Notification Service (WhatsApp & SMS)
export class DriverNotificationService {
  constructor() {
    this.outbox = [];
  }

  /**
   * Generates localized compliance WhatsApp messages
   */
  formatWhatsAppNotice(driver, truck, alert, language = 'ZU') {
    const reg = truck.registration;
    const loc = alert.location || 'N4 Corridor';
    let text = '';

    if (alert.type === 'SPEEDING_VIOLATION') {
      if (language === 'ZU') {
        text = `🚨 *Isexwayiso Se-FleetWatch (Speed)*\nSawubona ${driver.name}, iloli yakho *${reg}* igijima ngesivinini esingaphezu kwe-80 km/h eduze kwase-${loc}.\nYehlisa isivinini manje ukuvikela izinhlawulo ze-AARTO kanye nokuphepha komgwaqo.`;
      } else if (language === 'ST') {
        text = `🚨 *Temoso Ya FleetWatch (Lebelo)*\nDumela ${driver.name}, teraka ya hao *${reg}* e tsamaya ka lebelo le fetang 80 km/h haufi le ${loc}.\nTheola lebelo hona jwale bakeng sa polokeho ya hao.`;
      } else {
        text = `🚨 *FleetWatch Compliance Alert (Speed)*\nAttention ${driver.name}, truck *${reg}* has exceeded the 80 km/h heavy freight limit near ${loc}.\nPlease reduce speed immediately to avoid statutory AARTO fines.`;
      }
    } else if (alert.type === 'RTMS_FATIGUE_BREACH') {
      if (language === 'ZU') {
        text = `🛑 *Isikhathi Sokuphumula Se-RTMS*\nSawubona ${driver.name}, usushayele amahora angaphezu kuka-4 ngaphandle kokuphumula elolini *${reg}*.\nNgena e-Petroport eseduze (Rayton noma Bronkhorstspruit) uphumule imizuzu eyi-15 ngokomthetho.`;
      } else {
        text = `🛑 *RTMS Mandatory Rest Order*\nAttention ${driver.name}, you have driven >4 continuous hours in *${reg}*.\nPull into the nearest approved truck stop (Rayton or Bronkhorstspruit Petroport) for a mandatory 15-minute rest.`;
      }
    } else if (alert.type === 'UNAUTHORIZED_TOLL_BYPASS') {
      text = `⚠️ *URGENT: Unauthorized Route Detour*\nAttention ${driver.name}, truck *${reg}* has diverted onto an unapproved gravel route near Balmoral/R104.\nRejoin the N4 corridor immediately to prevent hijack exposure and company dispatch escalation.`;
    } else {
      text = `ℹ️ *FleetWatch Notice*\nDriver ${driver.name} (${reg}): Compliance alert triggered - ${alert.title}. Location: ${loc}.`;
    }

    return {
      to: driver.phone,
      driverName: driver.name,
      truckId: truck.id,
      registration: reg,
      language,
      platform: 'WHATSAPP_BUSINESS',
      message: text,
      timestamp: new Date().toISOString()
    };
  }

  /**
   * Generates compact SMS for low-connectivity rural zones
   */
  formatFallbackSms(driver, truck, alert) {
    return {
      to: driver.phone,
      platform: 'SMS_GATEWAY_SA',
      message: `FLEETWATCH ALERT: ${truck.registration} speed/route alert at ${alert.location || 'N4'}. Adhere to RTMS limits. Control: 0800 442 911`,
      timestamp: new Date().toISOString()
    };
  }

  /**
   * Dispatches or queues message
   */
  async sendDriverNotice(driver, truck, alert, language = 'ZU') {
    const payload = this.formatWhatsAppNotice(driver, truck, alert, language);
    this.outbox.unshift(payload);
    
    // In production, this calls Meta Graph API or Twilio WhatsApp API
    console.log(`[FleetWatch WhatsApp Dispatch] To: ${payload.to} | Lang: ${language} | Msg: ${payload.message.replace(/\n/g, ' ')}`);
    return payload;
  }

  getRecentDispatches(limit = 20) {
    return this.outbox.slice(0, limit);
  }
}

export const notificationService = new DriverNotificationService();
